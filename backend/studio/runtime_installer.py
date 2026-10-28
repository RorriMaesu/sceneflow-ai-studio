"""Pinned, isolated Windows runtimes. Existing ComfyUI and system Python are untouched."""
import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path, PurePosixPath, PureWindowsPath

import httpx
import psutil

from .config import ROOT
from . import storage, provider_workers
from .store import db, encode, now, uid

LOCKS = Path(__file__).resolve().parents[1] / 'runtime-locks'
PACK_RUNTIME = {'voices-small': 'speech', 'voices-character': 'speech', 'music': 'music', 'effects': 'effects','captions':'captions','alignment':'captions'}
IMPORTS = {'speech': ['qwen_tts', 'torch', 'soundfile'], 'music': ['acestep.handler', 'acestep.inference', 'acestep.llm_inference'], 'effects': ['moss_soundeffect_v2'],'captions':['transformers.models.qwen3_asr','torch','soundfile','librosa']}


class SetupUnconfirmed(Exception):
    pass


def migrate():
    provider_workers.migrate()
    with db.connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS runtime_install_jobs(id TEXT PRIMARY KEY,runtime_id TEXT,root_id TEXT,manifest_hash TEXT,status TEXT,step TEXT,error TEXT,owner TEXT,body TEXT,created REAL,updated REAL);
        CREATE TABLE IF NOT EXISTS runtime_quotes(id TEXT PRIMARY KEY,session TEXT,body TEXT,expires REAL,used INTEGER DEFAULT 0);
        ''')


def manifest(identifier):
    if identifier not in IMPORTS:
        raise ValueError('Choose a supported creation runtime.')
    data = json.loads((LOCKS / 'sources.json').read_text(encoding='utf-8'))
    lock = LOCKS / (identifier + '.txt')
    value = {'runtime': identifier, 'python': data['python'], 'requirements': data['runtimes'][identifier],
             'source': data['sources'][identifier], 'uv': data['uv']}
    if hashlib.sha256(lock.read_bytes()).hexdigest() != value['requirements']['requirements_sha256']:
        raise ValueError('The runtime lock changed unexpectedly. Repair or update the Studio application first.')
    value['hash'] = hashlib.sha256(encode(value).encode()).hexdigest()
    return value


def prefix(identifier, root_id):
    value = manifest(identifier)
    return storage.child(root_id, 'sceneflow/runtimes/' + identifier + '/' + value['hash'][:20] + '/.runtime', True).parent


def quote(identifier, root_id=None):
    migrate()
    if os.name != 'nt':
        raise ValueError('These pinned runtime packs currently support Windows PCs.')
    root_id = root_id or storage.route('models')
    if not root_id:
        raise ValueError('Choose your creation-tools folder first.')
    value = manifest(identifier)
    destination = prefix(identifier, root_id)
    storage.require_space(destination, 12 * 1024 ** 3)
    return {'runtime_id': identifier, 'root_id': root_id, 'manifest_hash': value['hash'],
            'download_bytes_upper': value['requirements']['download_bytes'] + (value['source'].get('archive_bytes', 0) if isinstance(value['source'], dict) else 0) + 120 * 1024 ** 2,
            'destination': str(destination), 'python': value['python'],
            'note': 'A separate program environment; working ComfyUI packages and system Python are preserved. Shared verified package caches avoid repeated downloads.'}


def queue(identifier, root_id=None):
    review = quote(identifier, root_id)
    active = db.one("SELECT * FROM runtime_install_jobs WHERE runtime_id=? AND root_id=? AND manifest_hash=? AND status IN ('queued','installing')", (identifier, review['root_id'], review['manifest_hash']))
    if active:
        return public(active)
    installed = db.one("SELECT * FROM provider_runtimes WHERE id=? AND state='ready'", (identifier,))
    if installed and json.loads(installed['manifest']).get('hash') == review['manifest_hash']:
        return {'id': None, 'runtime_id': identifier, 'status': 'completed', 'step': 'Program files are ready.'}
    identifier_job = uid()
    db.execute('INSERT INTO runtime_install_jobs VALUES(?,?,?,?,?,?,?,?,?,?,?)', (identifier_job, identifier, review['root_id'], review['manifest_hash'], 'queued', 'Waiting to set up program files.', None, None, encode(review), now(), now()))
    return public(db.one('SELECT * FROM runtime_install_jobs WHERE id=?', (identifier_job,)))


def public(row):
    return {k: v for k, v in row.items() if k not in {'owner', 'body'}}


def jobs():
    migrate()
    return [public(row) for row in db.all('SELECT * FROM runtime_install_jobs ORDER BY created DESC LIMIT 30')]


def update(identifier, status, step, error=None):
    db.execute('UPDATE runtime_install_jobs SET status=?,step=?,error=?,updated=? WHERE id=?', (status, step, error, now(), identifier))


def busy_reason():
    migrate()
    if db.one("SELECT id FROM runtime_install_jobs WHERE status='installing'"):
        return 'Setting up creation-tool program files. Graphics work will continue after setup finishes.'
    return None


def safe_unzip(archive, destination):
    storage.reject_links(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        files = source.infolist()
        if len(files) > 20000 or sum(f.file_size for f in files) > 1024 ** 3:
            raise ValueError('The provider source archive exceeds its reviewed extraction limit.')
        for item in files:
            path = PurePosixPath(item.filename)
            if path.is_absolute() or '..' in path.parts or '\\' in item.filename or PureWindowsPath(item.filename).drive or ':' in item.filename or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('The provider source archive contains an unsafe path.')
            target = storage.reject_links(destination.joinpath(*path.parts))
            if not target.is_relative_to(destination.resolve()):
                raise ValueError('The provider source archive escaped its folder.')
        source.extractall(destination)


async def download(url, destination, expected_size, expected_hash):
    storage.reject_links(destination)
    if destination.is_file() and destination.stat().st_size == expected_size:
        with destination.open('rb') as handle:
            if await asyncio.to_thread(lambda: hashlib.file_digest(handle, 'sha256').hexdigest()) == expected_hash:
                return destination
    storage.require_space(destination.parent, expected_size)
    part = destination.with_name(destination.name + '.part')
    storage.reject_links(part)
    digest = hashlib.sha256()
    count = 0
    async with httpx.AsyncClient(follow_redirects=True, timeout=120, trust_env=False) as client:
        async with client.stream('GET', url) as response:
            response.raise_for_status()
            with part.open('wb') as out:
                async for block in response.aiter_bytes(1024 ** 2):
                    count += len(block)
                    if count > expected_size:
                        raise ValueError('A program download exceeded its reviewed size.')
                    digest.update(block)
                    out.write(block)
    if count != expected_size or digest.hexdigest() != expected_hash:
        raise ValueError('A program download failed its integrity check. Retry setup; the working tools are preserved.')
    os.replace(part, destination)
    return destination


async def command(job, arguments, environment, folder, step, timeout=1200):
    update(job['id'], 'installing', step)
    log_path = folder / 'setup.log'
    with log_path.open('ab') as log:
        process = subprocess.Popen(arguments, cwd=folder, env=environment, stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=0x08000000 if os.name == 'nt' else 0)
        original = psutil.Process(process.pid)
        owner = {'pid': process.pid, 'created': original.create_time(), 'executable': original.exe(), 'arguments': arguments}
        db.execute('UPDATE runtime_install_jobs SET owner=? WHERE id=?', (encode(owner), job['id']))
        started = now()
        try:
            while process.poll() is None:
                if now() - started > timeout:
                    raise ValueError('Program setup reached its time limit. Your earlier tools are preserved; try setup again.')
                await asyncio.sleep(.5)
            if process.returncode:
                raise ValueError('This tool’s program setup could not finish. Your earlier tools are preserved. Advanced details are in ' + str(log_path))
        except BaseException:
            if process.poll() is None:
                if not await asyncio.to_thread(stop_previous, owner):
                    raise SetupUnconfirmed('A program setup process could not be verified as stopped. Review it before retrying.')
            raise
        finally:
            if process.poll() is not None:
                process.wait()
                db.execute('UPDATE runtime_install_jobs SET owner=NULL WHERE id=?', (job['id'],))


def stop_previous(owner):
    try:
        process = psutil.Process(owner['pid'])
        if abs(process.create_time() - owner['created']) >= .01:
            return True
        if process.cmdline() != owner['arguments'] or Path(process.exe()).resolve() != Path(owner['executable']).resolve():
            return False
        children = process.children(recursive=True)
        for child in reversed(children):
            try: child.kill()
            except psutil.NoSuchProcess: pass
        process.kill()
        _, alive = psutil.wait_procs([*children, process], timeout=20)
        return not alive
    except psutil.NoSuchProcess:
        return True
    except psutil.Error:
        return False


async def install(job):
    update(job['id'], 'installing', 'Preparing this tool’s separate program files.')
    identifier, root_id = job['runtime_id'], job['root_id']
    value = manifest(identifier)
    if value['hash'] != job['manifest_hash']:
        raise ValueError('The setup recipe changed. Review the new program setup first.')
    folder = prefix(identifier, root_id)
    folder.mkdir(parents=True, exist_ok=True)
    cache = storage.role_folder('cache')
    environment = storage.worker_environment()
    environment.update(UV_CACHE_DIR=str(cache / 'uv'), UV_PYTHON_INSTALL_DIR=str(storage.child(root_id, 'sceneflow/runtimes/python/.directory', True).parent),
                       UV_PYTHON_BIN_DIR=str(storage.child(root_id, 'sceneflow/runtimes/bin/.directory', True).parent),
                       UV_PYTHON_INSTALL_REGISTRY='false', UV_NO_PROGRESS='1', UV_HTTP_TIMEOUT='120', UV_HTTP_RETRIES='2')
    uv = ROOT / 'tools' / 'uv' / 'uv.exe'
    if not uv.is_file():
        update(job['id'], 'installing', 'Adding the portable setup helper.')
        uv.parent.mkdir(parents=True, exist_ok=True)
        archive = uv.parent / 'uv.zip'
        await download(value['uv']['url'], archive, value['uv']['bytes'], value['uv']['sha256'])
        await asyncio.to_thread(safe_unzip, archive, uv.parent)
        if not uv.is_file():
            found = next(uv.parent.rglob('uv.exe'), None)
            if not found:
                raise ValueError('The verified setup helper did not contain its Windows program.')
            shutil.copyfile(found, uv)
    await command(job, [str(uv), '-qq', 'python', 'install', value['python'], '--no-bin', '--no-registry', '--install-dir', environment['UV_PYTHON_INSTALL_DIR']], environment, folder, 'Adding a private Python runtime.')
    base = Path(environment['UV_PYTHON_INSTALL_DIR']) / ('cpython-' + value['python'] + '-windows-x86_64-none') / 'python.exe'
    if not base.is_file():
        raise ValueError('The private Python runtime is missing. Retry program setup.')
    env = folder / 'env'
    if not (env / 'Scripts/python.exe').exists():
        await command(job, [str(uv), '-qq', 'venv', '--python', str(base), str(env)], environment, folder, 'Creating this tool’s separate environment.')
    python = env / 'Scripts/python.exe'
    await command(job, [str(uv), '-qq', 'pip', 'sync', '--python', str(python), '--require-hashes', '--link-mode', 'hardlink', str(LOCKS / (identifier + '.txt'))], environment, folder, 'Installing verified program packages.')
    if isinstance(value['source'], dict):
        source = value['source']
        source_cache = cache / 'runtime-sources'
        source_cache.mkdir(parents=True, exist_ok=True)
        archive = source_cache / (identifier + '-' + source['revision'] + '.zip')
        await download(source['archive_url'], archive, source['archive_bytes'], source['archive_sha256'])
        unpack = folder / 'source'
        verified_source = unpack / 'sceneflow-source.sha256'
        if not verified_source.exists() or verified_source.read_text() != source['archive_sha256']:
            await asyncio.to_thread(safe_unzip, archive, unpack)
            verified_source.write_text(source['archive_sha256'])
        project = unpack / (source['repo'].split('/')[1] + '-' + source['revision'])
        if source.get('subdirectory'):
            project /= source['subdirectory']
        await command(job, [str(uv), '-qq', 'pip', 'install', '--python', str(python), '--no-deps', '--no-build-isolation', str(project)], environment, folder, 'Installing the pinned provider code.')
    code = 'import importlib,json,sys; modules=' + repr(IMPORTS[identifier]) + '; [importlib.import_module(x) for x in modules]; print(json.dumps({"python":sys.version,"imports":modules}))'
    await command(job, [str(python), '-I', '-c', code], environment, folder, 'Checking that the tool can start.', timeout=180)
    relative = str(python.relative_to(storage.checked_root(root_id))).replace('\\', '/')
    db.execute('INSERT OR REPLACE INTO provider_runtimes VALUES(?,?,?,?,?,?)', (identifier, root_id, relative, 'ready', encode(value), now()))
    update(job['id'], 'completed', 'Program files are ready. Run a short sample before production.')


class RuntimeManager:
    def __init__(self):
        self.task = None

    async def start(self):
        migrate()
        for row in db.all("SELECT * FROM runtime_install_jobs WHERE status='installing'"):
            stopped = not row['owner'] or await asyncio.to_thread(stop_previous, json.loads(row['owner']))
            update(row['id'], 'failed' if stopped else 'needs_attention', 'Setup was interrupted.', 'Review and retry setup. Existing working tools are preserved.' if stopped else 'A previous setup process could not be verified. Close it before continuing.')
        self.task = asyncio.create_task(self.loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass

    async def loop(self):
        while True:
            if not db.one("SELECT id FROM jobs WHERE status IN ('running','submitted','reconciling')") and not db.one("SELECT id FROM runtime_install_jobs WHERE status='needs_attention'"):
                job = db.one("SELECT * FROM runtime_install_jobs WHERE status='queued' ORDER BY created LIMIT 1")
                if job:
                    try:
                        await install(job)
                    except asyncio.CancelledError:
                        update(job['id'], 'failed', 'Setup was paused when Studio stopped.', 'Retry to continue using the verified package cache.')
                        raise
                    except SetupUnconfirmed as error:
                        update(job['id'], 'needs_attention', 'Setup needs attention.', str(error))
                    except Exception as error:
                        update(job['id'], 'failed', 'Setup needs attention.', str(error)[:700])
            await asyncio.sleep(1)


manager = RuntimeManager()
