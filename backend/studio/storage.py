"""Registered local folders. Browsers never supply filesystem authority."""
import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath, PureWindowsPath

from .config import ROOT, settings
from .store import db, encode, now, uid

ROLES = ('models', 'cache', 'images', 'videos', 'music', 'speech', 'effects', 'exports', 'backups')


def migrate():
    with db.connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS storage_roots(id TEXT PRIMARY KEY,path TEXT NOT NULL,identity TEXT NOT NULL,created REAL);
        CREATE TABLE IF NOT EXISTS storage_routes(role TEXT PRIMARY KEY,root_id TEXT NOT NULL REFERENCES storage_roots(id));
        CREATE TABLE IF NOT EXISTS scratch_locations(name TEXT PRIMARY KEY,reference TEXT NOT NULL);
        ''')


def reject_links(path):
    path = Path(path).absolute()
    for parent in (path, *path.parents):
        if parent.is_symlink() or (hasattr(parent, 'is_junction') and parent.is_junction()):
            raise ValueError('Choose a normal folder, rather than a linked folder.')
        if os.name == 'nt' and parent.exists():
            import stat
            if parent.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise ValueError('Linked folders cannot be used as a storage boundary.')
    return path.resolve()


def identity(path):
    return str(Path(path).stat().st_dev)


def grant(path):
    """Call only for a native-picker result, recommended install folder, or local CLI."""
    migrate()
    path = reject_links(path)
    if not path.is_dir():
        raise ValueError('That folder is unavailable. Reconnect the drive and choose it again.')
    if path == Path(path.anchor):
        raise ValueError('Choose a folder inside the drive, rather than the entire drive.')
    try:
        with tempfile.NamedTemporaryFile(prefix='.sceneflow-write-', dir=path):
            pass
    except OSError as error:
        raise ValueError('Studio cannot save in that folder. Choose another folder.') from error
    existing = db.one('SELECT * FROM storage_roots WHERE path=? AND identity=?', (str(path), identity(path)))
    if existing:
        return existing
    identifier = uid()
    db.execute('INSERT INTO storage_roots VALUES(?,?,?,?)', (identifier, str(path), identity(path), now()))
    return db.one('SELECT * FROM storage_roots WHERE id=?', (identifier,))


def choose_folder():
    if os.name != 'nt':
        raise ValueError('The local folder picker is available in the Windows app. Recommended folders still work.')
    try:
        import tkinter
        from tkinter import filedialog
        window = tkinter.Tk()
        window.withdraw()
        window.attributes('-topmost', True)
        try:
            value = filedialog.askdirectory(parent=window, title='Choose a SceneFlow library folder', mustexist=True)
        finally:
            window.destroy()
    except Exception as error:
        raise ValueError('The Windows folder picker could not open. Use recommended folders, or run the local setup tool.') from error
    return grant(value) if value else None


def checked_root(identifier):
    migrate()
    row = db.one('SELECT * FROM storage_roots WHERE id=?', (identifier,))
    if not row:
        raise ValueError('Choose a folder using the local folder picker first.')
    path = reject_links(row['path'])
    if not path.is_dir() or identity(path) != row['identity']:
        raise ValueError('The selected storage drive is missing or changed. Reconnect it in Setup.')
    return path


def child(identifier, relative, create=False):
    root = checked_root(identifier)
    value = str(relative).replace('\\', '/')
    parts = PurePosixPath(value)
    if not value or parts.is_absolute() or PureWindowsPath(value).drive or any(p in ('..', '.') for p in value.split('/')) or ':' in value or '\x00' in value:
        raise ValueError('That file is outside the selected Studio folder.')
    path = root.joinpath(*parts.parts)
    reject_links(path)
    if not path.resolve().is_relative_to(root):
        raise ValueError('That file is outside the selected Studio folder.')
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
        reject_links(path.parent)
    return path


def use_routes(routes):
    migrate()
    if not isinstance(routes, dict) or set(routes) - set(ROLES):
        raise ValueError('Choose one of the supported storage categories.')
    for identifier in routes.values():
        checked_root(identifier)
    with db.connect(True) as con:
        for role, identifier in routes.items():
            con.execute('INSERT OR REPLACE INTO storage_routes VALUES(?,?)', (role, identifier))
    return status()


def recommended():
    path = ROOT / 'library'
    path.mkdir(parents=True, exist_ok=True)
    root = grant(path)
    use_routes({role: root['id'] for role in ROLES})
    return status()


def route(role):
    if role not in ROLES:
        raise ValueError('Unknown storage category.')
    migrate()
    row = db.one('SELECT root_id FROM storage_routes WHERE role=?', (role,))
    return row['root_id'] if row else None


def role_folder(role):
    identifier = route(role)
    if identifier:
        folder = child(identifier, 'sceneflow/' + role + '/.folder', True).parent
    else:
        folder = ROOT / ('temp' if role == 'cache' else role)
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def media_location(project_id, scene_id, kind, identifier, suffix, metadata=None):
    from uuid import UUID
    project_id = str(UUID(project_id))
    if scene_id:
        scene_id = str(UUID(scene_id))
    role = {'image': 'images', 'video': 'videos', 'export': 'exports'}.get(kind, (metadata or {}).get('role', 'music'))
    role = {'voiceover': 'speech', 'ambience': 'effects'}.get(role, role)
    if role not in ROLES:
        role = 'music'
    selected = route(role)
    if not selected:
        return None
    relative = f'sceneflow/{role}/{project_id}/{scene_id or "production"}/{identifier}{suffix}'
    return '@' + selected + '/' + relative, child(selected, relative, True)


def resolve_media(value):
    if not str(value).startswith('@'):
        return None
    identifier, separator, relative = str(value)[1:].partition('/')
    if not separator or not relative.startswith('sceneflow/'):
        raise ValueError('This file is outside registered Studio media storage.')
    return child(identifier, relative)


def status():
    migrate()
    roots = []
    for row in db.all('SELECT * FROM storage_roots ORDER BY created'):
        try:
            path = checked_root(row['id'])
            space = shutil.disk_usage(path)
            roots.append({**row, 'available': True, 'free_bytes': space.free, 'total_bytes': space.total})
        except (ValueError, OSError):
            roots.append({**row, 'available': False, 'free_bytes': None})
    return {'roots': roots, 'routes': {row['role']: row['root_id'] for row in db.all('SELECT * FROM storage_routes')}, 'roles': ROLES,
            'existing_media_note': 'Folder choices apply to new files. Existing media stays registered in its original folder.'}


def require_space(folder, required):
    free = shutil.disk_usage(folder).free
    reserve = int(settings['disk_reserve_gb'] * 1024 ** 3)
    if free < required + reserve:
        raise ValueError('Not enough space in the selected folder. Choose another drive or free space, then retry.')
    return free


def worker_environment():
    cache = role_folder('cache')
    return {**os.environ, 'TEMP': str(cache), 'TMP': str(cache), 'HF_HOME': str(cache / 'huggingface'),
            'TORCH_HOME': str(cache / 'torch'), 'PIP_CACHE_DIR': str(cache / 'pip'),
            'XDG_CACHE_HOME': str(cache / 'xdg'), 'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1',
            'PYTHONIOENCODING': 'utf-8', 'HF_HUB_DISABLE_TELEMETRY': '1'}


def cache_file(name):
    if Path(name).name != name or PureWindowsPath(name).name != name or ':' in name or '\x00' in name:
        raise ValueError('Invalid temporary file name.')
    return role_folder('cache') / name


def export_folder(job_id):
    name = 'export-' + job_id
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in name):
        raise ValueError('Invalid export task.')
    migrate()
    existing = db.one('SELECT reference FROM scratch_locations WHERE name=?', (name,))
    if existing:
        reference = existing['reference']
        return resolve_media(reference) if reference.startswith('@') else ROOT / 'temp' / name
    identifier = route('cache')
    reference = '@' + identifier + '/sceneflow/cache/' + name if identifier else 'temp/' + name
    db.execute('INSERT OR IGNORE INTO scratch_locations VALUES(?,?)', (name, reference))
    return resolve_media(reference) if identifier else ROOT / 'temp' / name


def backup_files():
    migrate()
    folders = [ROOT / 'backups']
    for row in db.all('SELECT id FROM storage_roots'):
        try:
            folders.append(child(row['id'], 'sceneflow/backups'))
        except (OSError, ValueError):
            continue
    values = {}
    for folder in folders:
        for path in folder.glob('*.sceneflow.zip'):
            reject_links(path)
            values[path.name] = path
    return list(values.values())


def backup_file(identifier):
    from uuid import UUID
    name = str(UUID(identifier)) + '.sceneflow.zip'
    found = next((p for p in backup_files() if p.name == name), None)
    if found is None:
        raise FileNotFoundError('Backup unavailable. Reconnect its drive or choose a backup file to restore.')
    return found
