"""Owned subprocess boundary for isolated model runtimes; no browser commands."""
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
from pathlib import Path

import psutil

from .config import ROOT
from . import storage
from .store import db, encode, now


class CreationCancelled(Exception):
    pass


def migrate(store=None):
    with (store or db).connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS provider_runtimes(id TEXT PRIMARY KEY,root_id TEXT,python_relative TEXT,state TEXT,manifest TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS provider_workers(job_id TEXT PRIMARY KEY,pid INTEGER,created REAL,executable TEXT,request_path TEXT,nonce TEXT,status TEXT,updated REAL);
        ''')


def runtime_python(identifier):
    migrate()
    row = db.one("SELECT * FROM provider_runtimes WHERE id=? AND state='ready'", (identifier,))
    if not row:
        raise ValueError('This tool needs its isolated runtime setup first. Open Setup & downloads.')
    relative = row['python_relative']
    if not relative.startswith('sceneflow/runtimes/' + identifier + '/'):
        raise ValueError('The runtime path is outside its registered tool folder.')
    path = storage.child(row['root_id'], relative)
    if not path.is_file():
        raise ValueError('This tool runtime is missing. Reconnect its drive or repair it in Setup.')
    return path


def process_for(row):
    try:
        process = psutil.Process(row['pid'])
        if abs(process.create_time() - row['created']) >= .01:
            return None
        return process
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def owned_process(row):
    process = process_for(row)
    if process is None:
        return None
    try:
        arguments = process.cmdline()
        if str(Path(process.exe()).resolve()).casefold() != str(Path(row['executable']).resolve()).casefold():
            return None
        if row['request_path'] not in arguments:
            return None
        request_path = Path(row['request_path'])
        storage.reject_links(request_path)
        value = json.loads(request_path.read_text(encoding='utf-8'))
        if value.get('job_id') != row['job_id'] or value.get('nonce') != row['nonce']:
            return None
        return process
    except (psutil.Error, OSError, ValueError):
        return None


def stop_owned(row):
    process = owned_process(row)
    if process is None:
        if process_for(row) is None:
            return True
        return False
    # Descendants are captured through the verified original parent, not a name search.
    children = process.children(recursive=True)
    for child in reversed(children):
        try:
            if child.create_time() >= row['created']:
                child.kill()
        except psutil.NoSuchProcess:
            pass
    try:
        process.kill()
    except psutil.NoSuchProcess:
        pass
    _, running = psutil.wait_procs([*children, process], timeout=15)
    return not running


def recovery(store=None):
    store=store or db
    migrate(store)
    for row in store.all("SELECT * FROM provider_workers WHERE status='running'"):
        if stop_owned(row):
            store.execute("UPDATE provider_workers SET status='stopped',updated=? WHERE job_id=?", (now(), row['job_id']))
            store.execute("UPDATE jobs SET status='needs_attention',error='Studio restarted during this sound/voice task. Saved results are kept; review before retrying.',finished=? WHERE id=? AND status IN ('running','submitted','reconciling')", (now(), row['job_id']))
        else:
            store.execute("UPDATE jobs SET error='A previous tool process could not be verified. New graphics work waits until it is safely stopped.' WHERE id=?", (row['job_id'],))


def active_reason(except_job=None):
    migrate()
    for row in db.all("SELECT * FROM provider_workers WHERE status='running'"):
        if row['job_id'] == except_job:
            continue
        if process_for(row) is not None:
            return 'Waiting for the previous Studio creation tool to release the graphics card.'
        db.execute("UPDATE provider_workers SET status='stopped',updated=? WHERE job_id=?", (now(), row['job_id']))
    return None


async def run(job, runtime_id, inputs, timeout=1800):
    """Caller supplies typed provider inputs, never a command or a runtime path."""
    migrate()
    from .resource_broker import broker
    if broker.job_id != job['id']:
        raise ValueError('This task must enter the shared graphics queue before a model can start.')
    python = runtime_python(runtime_id)
    script = ROOT / 'backend' / ('caption_worker.py' if runtime_id=='captions' else 'provider_worker.py')
    if not script.is_file():
        raise ValueError('This creation provider is not included in the installed release yet.')
    folder = storage.cache_file('worker-' + job['id'])
    folder.mkdir(parents=True, exist_ok=True)
    storage.reject_links(folder)
    request = folder / 'input.json'
    result = folder / 'result.json'
    nonce = secrets.token_hex(24)
    body = {**inputs, 'job_id': job['id'], 'nonce': nonce, 'result_path': str(result), 'output_dir': str(folder)}
    request.write_text(encode(body), encoding='utf-8')
    request_hash = hashlib.sha256(request.read_bytes()).hexdigest()
    result.unlink(missing_ok=True)
    environment = storage.worker_environment()
    environment.update(TORCHDYNAMO_DISABLE='1', TOKENIZERS_PARALLELISM='false', OMP_NUM_THREADS='4',SCENEFLOW_ADMITTED_JOB=job['id'])
    with (folder / 'worker.log').open('wb') as log:
        process = subprocess.Popen([str(python), '-I', str(script), '--input', str(request), '--sha256', request_hash],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   cwd=folder, env=environment, creationflags=0x08000000 if os.name == 'nt' else 0)
        try:
            owner = psutil.Process(process.pid)
            row = {'job_id': job['id'], 'pid': process.pid, 'created': owner.create_time(), 'executable': owner.exe(),
                   'request_path': str(request), 'nonce': nonce, 'status': 'running', 'updated': now()}
            db.execute('INSERT OR REPLACE INTO provider_workers VALUES(?,?,?,?,?,?,?,?)', tuple(row.values()))
            started = now()
            while process.poll() is None:
                progress_file=folder/'progress.json'
                try:
                    if progress_file.is_file() and progress_file.stat().st_size<4096:
                        progress=json.loads(progress_file.read_text(encoding='utf-8'));fraction=progress.get('progress')
                        if progress.get('job_id')==job['id'] and progress.get('nonce')==nonce and isinstance(fraction,(int,float)) and 0<=fraction<=.95:
                            db.execute('UPDATE jobs SET progress=? WHERE id=?',(fraction,job['id']))
                except (OSError,ValueError):pass
                current = db.one('SELECT cancel_requested FROM jobs WHERE id=?', (job['id'],))
                if current and current['cancel_requested']:
                    if not await asyncio.to_thread(stop_owned, row):
                        raise ValueError('The tool could not be verified as stopped. Graphics work remains reserved for review.')
                    raise CreationCancelled('This creation task was cancelled.')
                if now() - started > timeout:
                    if not await asyncio.to_thread(stop_owned, row):
                        raise ValueError('The timed-out tool could not be verified as stopped. Review it before retrying.')
                    raise ValueError('The tool reached its time limit. Your inputs and earlier takes are preserved.')
                await asyncio.sleep(.5)
            if process.returncode or not result.is_file():
                detail = json.loads(result.read_text()) if result.is_file() else {}
                raise ValueError(detail.get('error', 'The creation tool stopped before saving a verified result. Open its local log in Advanced setup.'))
            value = json.loads(result.read_text(encoding='utf-8'))
            if value.get('job_id') != job['id'] or value.get('nonce') != nonce:
                raise ValueError('The creation result belongs to a different task.')
            for artifact in value.get('files', []):
                path = storage.reject_links(folder / artifact['name'])
                if not path.is_relative_to(folder.resolve()) or not path.is_file():
                    raise ValueError('A provider returned a file outside its owned task folder.')
            return value, folder
        except BaseException:
            if process.poll() is None:
                if 'row' not in locals():
                    # The native Popen handle belongs to the process just created here.
                    process.kill()
                    await asyncio.to_thread(process.wait, 15)
                    stopped = True
                else:
                    stopped = await asyncio.to_thread(stop_owned, row)
                if not stopped:
                    # Keep running status so admission blocks a second model after this failure.
                    raise ValueError('The owned creation process is still unconfirmed. Graphics work is paused for recovery.')
            raise
        finally:
            if process.poll() is not None:
                process.wait()
                db.execute("UPDATE provider_workers SET status='stopped',updated=? WHERE job_id=?", (now(), job['id']))
