"""Pinned pack metadata and downloads. No arbitrary URLs or executable installers."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

import httpx

from .config import ROOT
from .store import db, encode, now, uid
from . import storage

CATALOG_FILE = Path(__file__).with_name('model_catalog.json')


def catalog():
    return json.loads(CATALOG_FILE.read_text(encoding='utf-8'))['packs']


def pack(identifier):
    value = next((p for p in catalog() if p['id'] == identifier), None)
    if not value:
        raise ValueError('Choose a creation tool from the Studio library.')
    return value


def migrate():
    with db.connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS install_quotes(id TEXT PRIMARY KEY,session TEXT,body TEXT,expires REAL);
        CREATE TABLE IF NOT EXISTS model_downloads(id TEXT PRIMARY KEY,pack_id TEXT,revision TEXT,root_id TEXT,status TEXT,body TEXT,bytes_done INTEGER,bytes_total INTEGER,error TEXT,created REAL,updated REAL,cancel_requested INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS model_installs(pack_id TEXT,revision TEXT,root_id TEXT,body TEXT,verified REAL,PRIMARY KEY(pack_id,revision,root_id));
        CREATE TABLE IF NOT EXISTS model_update_checks(pack_id TEXT PRIMARY KEY,body TEXT,checked REAL);
        ''')


def install_path(value, root_id):
    return storage.child(root_id, f'sceneflow/models/{value["id"]}/{value["revision"]}/.pack', True).parent


def file_path(value, root_id, item):
    return storage.child(root_id, f'sceneflow/models/{value["id"]}/{value["revision"]}/{item["path"]}', True)


def matches(path, item):
    if not path.is_file() or path.stat().st_size != item['bytes']:
        return False
    with path.open('rb') as source:
        if item.get('sha256'):
            return hashlib.file_digest(source, 'sha256').hexdigest() == item['sha256']
        digest = hashlib.sha1(('blob ' + str(item['bytes']) + '\0').encode())
        while block := source.read(1024 ** 2):
            digest.update(block)
        return digest.hexdigest() == item['git_blob_sha1']


def manifest_hash(value):
    return hashlib.sha256(encode(value).encode()).hexdigest()


def list_packs():
    migrate()
    result = []
    for value in catalog():
        install = db.one('SELECT * FROM model_installs WHERE pack_id=? AND revision=? ORDER BY verified DESC', (value['id'], value['revision']))
        state = 'needs_download'
        reason = value.get('setup_note', 'Download the tool, then run a short setup test.')
        if install:
            try:
                storage.checked_root(install['root_id'])
                state = 'needs_test'
                reason = 'Files verified. Install the isolated runtime and run a short sample before production.'
                from .audio_engine import PROVIDERS, qualification, runtime_record
                if value['id'] in PROVIDERS:
                    if not runtime_record(value['id']):
                        state, reason = 'needs_runtime', 'Model files downloaded. Finish program setup, then run a sample.'
                    elif qualification(value['id']):
                        state, reason = 'ready', 'A sample passed on this PC. Listen to it before using this tool in your story.'
                    else:
                        reason = 'Program and model files are ready. Run a sample to check this PC.'
                elif value['id'] in {'captions','alignment'}:
                    from .caption_engine import runtime,qualification as caption_qualification
                    if not runtime():state,reason='needs_runtime','Model files downloaded. Finish the separate caption program setup.'
                    elif caption_qualification(value['id']):state,reason='ready','A short recording passed. Review caption words and timings before applying them.'
                    else:state,reason='needs_test','In a sequence, open Edit → Captions and test a recording up to 30 seconds. Recognition produces a draft for review.'
            except ValueError:
                state = 'storage_missing'
                reason = 'Reconnect the drive that holds this tool.'
        if value.get('blocked'):
            state = 'setup_required'
            reason = value['blocked']
        result.append({**{k: v for k, v in value.items() if k != 'files'}, 'bytes': sum(f['bytes'] for f in value.get('files', [])),
                       'state': state, 'reason': reason, 'installed': bool(install),
                       'update': db.one('SELECT body,checked FROM model_update_checks WHERE pack_id=?', (value['id'],))})
    return result


def quote_install(identifier, session, root_id=None):
    migrate()
    value = pack(identifier)
    if value.get('blocked') or value.get('gated'):
        raise ValueError(value.get('blocked') or 'This tool needs official account/license setup before Studio can download it.')
    root_id = root_id or storage.route('models')
    if not root_id:
        raise ValueError('Choose your model folder in Setup first.')
    storage.checked_root(root_id)
    if not value.get('files') or any(not f.get('sha256') and not f.get('git_blob_sha1') for f in value['files']):
        raise ValueError('This pack is missing verification information. Check for a qualified Studio update.')
    destination = install_path(value, root_id)
    # Existing bytes count as reusable only after verification, not just a size match.
    installed=db.one('SELECT body FROM model_installs WHERE pack_id=? AND revision=? AND root_id=?',(identifier,value['revision'],root_id))
    trusted=json.loads(installed['body']) if installed else {}
    stamps=trusted.get('fingerprints',{}) if trusted.get('manifest_hash')==manifest_hash(value) else {}
    def reusable(item):
        path=file_path(value,root_id,item)
        if path.is_file():
            info=path.stat()
            if stamps.get(item['path'])==[info.st_size,info.st_mtime_ns]:return True
        return matches(path,item)
    missing = [f for f in value['files'] if not reusable(f)]
    body = {'pack_id': identifier, 'revision': value['revision'], 'root_id': root_id,
            'manifest_hash': manifest_hash(value), 'download_bytes': sum(f['bytes'] for f in missing),
            'pack_bytes': sum(f['bytes'] for f in value['files']), 'files': value['files'],
            'destination': str(destination), 'license': value['license'], 'source': value['source'],
            'note': 'Model files and pinned support files only; downloading does not execute them. Runtime setup and a sample test follow.'}
    body['free_bytes'] = storage.require_space(destination, body['download_bytes'])
    identifier = uid()
    db.execute('INSERT INTO install_quotes VALUES(?,?,?,?)', (identifier, session['hash'], encode(body), now() + 1800))
    return {'id': identifier, **body, 'expires_in': 1800}


def start_download(quote_id, session):
    migrate()
    row = db.one('SELECT * FROM install_quotes WHERE id=? AND session=? AND expires>?', (quote_id, session['hash'], now()))
    if not row:
        raise ValueError('That download review expired. Review the size and folder again.')
    body = json.loads(row['body'])
    value = pack(body['pack_id'])
    if manifest_hash(value) != body['manifest_hash']:
        raise ValueError('The tool changed since your review. Review the new download first.')
    storage.require_space(install_path(value, body['root_id']), body['download_bytes'])
    with db.connect(True) as con:
        active = con.execute("SELECT * FROM model_downloads WHERE pack_id=? AND revision=? AND root_id=? AND status IN ('queued','downloading','verifying')", (value['id'], value['revision'], body['root_id'])).fetchone()
        if active:
            return dict(active)
        identifier = uid()
        body['session'] = session['hash']
        con.execute('INSERT INTO model_downloads VALUES(?,?,?,?,?,?,?,?,?,?,?,0)',
                    (identifier, value['id'], value['revision'], body['root_id'], 'queued', encode(body), 0, body['pack_bytes'], None, now(), now()))
        con.execute('DELETE FROM install_quotes WHERE id=?', (quote_id,))
    return db.one('SELECT * FROM model_downloads WHERE id=?', (identifier,))


def downloads():
    migrate()
    return [{k: v for k, v in row.items() if k != 'body'} for row in db.all('SELECT * FROM model_downloads ORDER BY created DESC LIMIT 50')]


def cancelled(identifier, session_hash):
    row = db.one('SELECT cancel_requested FROM model_downloads WHERE id=?', (identifier,))
    return not row or row['cancel_requested'] or not db.one('SELECT hash FROM sessions WHERE hash=? AND expires>?', (session_hash, now()))


def update(identifier, status, **values):
    allowed = {'bytes_done', 'error'}
    if set(values) - allowed:
        raise ValueError('Unsupported download update.')
    entries = {'status': status, 'updated': now(), **values}
    db.execute('UPDATE model_downloads SET ' + ','.join(k + '=?' for k in entries) + ' WHERE id=?', (*entries.values(), identifier))


class DownloadPaused(Exception):
    pass


class DownloadManager:
    def __init__(self):
        self.task = None

    async def start(self):
        migrate()
        db.execute("UPDATE model_downloads SET status='paused',error='Studio restarted. Resume the download to continue verified partial files.' WHERE status IN ('downloading','verifying')")
        self.task = asyncio.create_task(self.loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def loop(self):
        while True:
            row = db.one("SELECT * FROM model_downloads WHERE status='queued' ORDER BY created LIMIT 1")
            if row:
                try:
                    await self.execute(row)
                except DownloadPaused:
                    update(row['id'], 'paused', error='Download paused. Verified files and partial progress are kept.')
                except asyncio.CancelledError:
                    update(row['id'], 'paused', error='Studio stopped. Resume to continue the download.')
                    raise
                except Exception as error:
                    update(row['id'], 'failed', error=str(error)[:700])
            await asyncio.sleep(1)

    async def execute(self, row):
        value = pack(row['pack_id'])
        body = json.loads(row['body'])
        if manifest_hash(value) != body['manifest_hash']:
            raise ValueError('The model pack changed. Review a fresh download quote.')
        done = 0
        update(row['id'], 'downloading', error=None)
        async with httpx.AsyncClient(follow_redirects=True, timeout=httpx.Timeout(90, connect=20), trust_env=False) as client:
            for item in value['files']:
                if cancelled(row['id'], body['session']):
                    raise DownloadPaused()
                target = file_path(value, row['root_id'], item)
                if await asyncio.to_thread(matches, target, item):
                    done += item['bytes']
                    update(row['id'], 'downloading', bytes_done=done)
                    continue
                temporary = target.with_name(target.name + '.part')
                sidecar = temporary.with_name(temporary.name + '.json')
                storage.reject_links(temporary)
                storage.reject_links(sidecar)
                descriptor = {'revision': value['revision'], 'path': item['path'], 'bytes': item['bytes'], 'sha256': item.get('sha256'), 'git_blob_sha1': item.get('git_blob_sha1')}
                try:
                    resume = temporary.stat().st_size if temporary.exists() and sidecar.exists() and json.loads(sidecar.read_text()) == descriptor else 0
                except (ValueError, OSError):
                    resume = 0
                if resume == item['bytes'] and await asyncio.to_thread(matches, temporary, item):
                    os.replace(temporary, target)
                    sidecar.unlink(missing_ok=True)
                    done += item['bytes']
                    update(row['id'], 'downloading', bytes_done=done)
                    continue
                if resume > item['bytes']:
                    resume = 0
                storage.require_space(target.parent, item['bytes'] - resume)
                sidecar.write_text(encode(descriptor), encoding='utf-8')
                url = 'https://huggingface.co/' + value['repo'] + '/resolve/' + value['revision'] + '/' + quote(item['path'], safe='/')
                async with client.stream('GET', url, headers={'Range': f'bytes={resume}-'} if resume else {}) as response:
                    response.raise_for_status()
                    if resume and (response.status_code != 206 or not response.headers.get('content-range', '').startswith(f'bytes {resume}-')):
                        resume = 0
                    if not resume and response.status_code == 206:
                        raise ValueError('The download server returned an unexpected byte range. Retry the download.')
                    received = resume
                    last = 0
                    with temporary.open('ab' if resume else 'wb') as output:
                        async for block in response.aiter_bytes(1024 ** 2):
                            received += len(block)
                            if received > item['bytes']:
                                raise ValueError('A model file exceeded its reviewed size. The file was not installed.')
                            output.write(block)
                            if now() - last >= 1:
                                storage.checked_root(row['root_id'])
                                if cancelled(row['id'], body['session']):
                                    raise DownloadPaused()
                                storage.require_space(target.parent, 0)
                                update(row['id'], 'downloading', bytes_done=done + received)
                                last = now()
                update(row['id'], 'verifying', bytes_done=done + received)
                if not await asyncio.to_thread(matches, temporary, item):
                    # A failed hash must never be resumed as a valid prefix.
                    temporary.rename(temporary.with_name(temporary.name + '.invalid-' + uid()))
                    raise ValueError('A file did not pass verification. The incomplete tool was not installed; retry downloads a fresh copy.')
                os.replace(temporary, target)
                sidecar.unlink(missing_ok=True)
                done += item['bytes']
        if cancelled(row['id'], body['session']):
            raise DownloadPaused()
        stamps={item['path']:[file_path(value,row['root_id'],item).stat().st_size,file_path(value,row['root_id'],item).stat().st_mtime_ns] for item in value['files']}
        db.execute('INSERT OR REPLACE INTO model_installs VALUES(?,?,?,?,?)', (value['id'], value['revision'], row['root_id'], encode({'manifest_hash': manifest_hash(value),'fingerprints':stamps}), now()))
        update(row['id'], 'completed', bytes_done=done, error=None)
        db.event('model.downloaded', {'pack_id': value['id'], 'download_id': row['id']})


manager = DownloadManager()


async def check_updates():
    migrate()
    result = []
    async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
        for value in catalog():
            if not value.get('repo'):
                continue
            try:
                response = await client.get('https://huggingface.co/api/models/' + value['repo'])
                response.raise_for_status()
                latest = response.json().get('sha')
                body = {'latest_revision': latest, 'installed_catalog_revision': value['revision'], 'update_available': bool(latest and latest != value['revision']), 'note': 'Metadata only. Working tools and productions were not changed.'}
            except (httpx.HTTPError, ValueError):
                body = {'error': 'The update server could not be reached. Installed tools still work.'}
            db.execute('INSERT OR REPLACE INTO model_update_checks VALUES(?,?,?)', (value['id'], encode(body), now()))
            result.append({'pack_id': value['id'], **body})
    return result
