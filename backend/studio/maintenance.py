"""Explicit, reversible quarantine of old terminal export scratch folders only."""
import json
import os
import stat
import time
import threading
from functools import wraps
from pathlib import Path

from fastapi import APIRouter, Depends

from .config import ROOT
from .security import require_session
from .store import db, uid

router = APIRouter(prefix='/api/maintenance')
TERMINAL = {'completed', 'failed', 'cancelled', 'superseded'}
operation_lock = threading.RLock()


def serialized(function):
    @wraps(function)
    def run(*args, **kwargs):
        with operation_lock:return function(*args, **kwargs)
    return run


def safe_path(root, path):
    root = Path(root).absolute(); path = Path(path).absolute()
    if path == root or not path.is_relative_to(root):
        raise ValueError('Maintenance paths must stay inside their owned folder.')
    for part in [root, *reversed(list(path.parents)[:len(path.parts)-len(root.parts)-1]), path]:
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise ValueError('Linked folders cannot be maintained automatically.')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Maintenance path escaped its owned folder.')
    return path


def fingerprint(path):
    items = []
    for parent, directories, files in os.walk(path, followlinks=False):
        for name in sorted(directories + files):
            entry = safe_path(path, Path(parent)/name); info = entry.lstat()
            if not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode)):
                raise ValueError('Unsupported scratch file.')
            items.append([str(entry.relative_to(path)), info.st_size, info.st_mtime_ns])
            if len(items) > 5000:raise ValueError('Scratch folder exceeds the maintenance scan limit.')
    return sorted(items)


def manifest_path(identifier):
    import uuid
    try:identifier = str(uuid.UUID(identifier))
    except (ValueError, TypeError):raise ValueError('Invalid maintenance record.')
    return safe_path(ROOT, ROOT/'backups'/'cleanup'/identifier/'manifest.json')


def save(record):
    path = manifest_path(record['id']); path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp'); temporary.write_text(json.dumps(record, indent=2), encoding='utf-8'); os.replace(temporary, path)


def read(identifier, session, owner=True):
    record = json.loads(manifest_path(identifier).read_text(encoding='utf-8'))
    if owner and record['session'] != session['hash']:raise ValueError('Use the browser that prepared this maintenance review.')
    return record


def eligible(job_id):
    job = db.one('SELECT kind,status,finished FROM jobs WHERE id=?', (job_id,))
    return bool(job and job['kind'] == 'export' and job['status'] in TERMINAL and job['finished'] and job['finished'] < time.time()-86400)


@router.post('/review')
def review(session=Depends(require_session)):
    candidates = []
    scratch = safe_path(ROOT, ROOT/'temp')
    for path in sorted(scratch.glob('export-*')):
        job_id = path.name.removeprefix('export-')
        if not eligible(job_id):continue
        path = safe_path(scratch, path)
        if not path.is_dir() or path.stat().st_mtime > time.time()-86400:continue
        tree = fingerprint(path)
        candidates.append({'name':path.name, 'job_id':job_id, 'tree':tree, 'bytes':sum(row[1] for row in tree if (path/row[0]).is_file()), 'moved':False})
    record = {'id':uid(), 'session':session['hash'], 'created':time.time(), 'state':'reviewed', 'items':candidates}
    save(record)
    return {'id':record['id'], 'items':[{'name':item['name'], 'bytes':item['bytes']} for item in candidates], 'bytes':sum(i['bytes'] for i in candidates)}


@router.post('/{identifier}/quarantine')
@serialized
def quarantine(identifier:str, session=Depends(require_session)):
    record = read(identifier, session)
    if record['state'] != 'reviewed' or time.time()-record['created'] > 900:raise ValueError('Prepare a fresh maintenance review first.')
    for item in record['items']:
        source = safe_path(ROOT, ROOT/'temp'/item['name'])
        if not eligible(item['job_id']) or not source.is_dir() or fingerprint(source) != item['tree']:raise ValueError('Scratch files changed. Prepare a fresh review.')
        target = safe_path(ROOT, manifest_path(identifier).parent/'files'/item['name'])
        if target.exists():raise ValueError('Quarantine destination already exists.')
    record['state'] = 'moving'; save(record)
    for item in record['items']:
        source = safe_path(ROOT, ROOT/'temp'/item['name']); target = safe_path(ROOT, manifest_path(identifier).parent/'files'/item['name'])
        target.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, target); item['moved'] = True; save(record)
    record['state'] = 'quarantined'; save(record)
    return {'id':identifier, 'state':record['state'], 'folders':len(record['items'])}


@router.get('/history')
def history(session=Depends(require_session)):
    base = safe_path(ROOT, ROOT/'backups'/'cleanup')
    if not base.exists():return []
    result = []
    for path in base.glob('*/manifest.json'):
        try:
            record = read(path.parent.name, session, owner=False)
            if record['state'] != 'reviewed':result.append({key:record[key] for key in ['id', 'created', 'state']})
        except (ValueError, OSError, KeyError):continue
    return sorted(result, key=lambda r:r['created'], reverse=True)[:20]


@router.post('/{identifier}/restore')
@serialized
def restore(identifier:str, session=Depends(require_session)):
    record = read(identifier, session, owner=False)
    if record['state'] not in ['moving','quarantined','restoring']:raise ValueError('This record has no quarantined files to restore.')
    moves = []
    for item in record['items']:
        source = safe_path(ROOT, manifest_path(identifier).parent/'files'/item['name']); target = safe_path(ROOT, ROOT/'temp'/item['name'])
        if source.exists():
            if target.exists():raise ValueError('A scratch folder now occupies the original location. Nothing was overwritten.')
            if fingerprint(source) != item['tree']:raise ValueError('Quarantined files changed. Inspect the local backup before restoring.')
            moves.append((source,target))
    record['state'] = 'restoring'; save(record)
    for source,target in moves:os.replace(source,target)
    record['state'] = 'restored'; save(record)
    return {'id':identifier, 'state':'restored', 'folders':len(moves)}
