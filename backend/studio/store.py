import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .config import ROOT


def uid():
    return str(uuid.uuid4())


def now():
    return time.time()


def encode(value):
    return json.dumps(value, separators=(',', ':'), ensure_ascii=False)


class Conflict(Exception):
    pass


class Store:
    def __init__(self, path=None):
        self.path = path or ROOT / 'database' / 'studio.sqlite3'
        self.migrate()

    @contextmanager
    def connect(self, write=False):
        con = sqlite3.connect(str(self.path), timeout=15)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=15000')
        if write:
            con.execute('BEGIN IMMEDIATE')
        try:
            yield con
            con.commit()
        except BaseException:
            con.rollback()
            raise
        finally:
            con.close()

    def migrate(self):
        with self.connect() as con:
            con.execute('PRAGMA journal_mode=WAL')
            con.executescript('''
            CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY, applied REAL);
            CREATE TABLE IF NOT EXISTS projects(id TEXT PRIMARY KEY,title TEXT NOT NULL,brief TEXT NOT NULL,mode TEXT NOT NULL DEFAULT 'hybrid',revision INTEGER NOT NULL DEFAULT 1,settings TEXT NOT NULL,archived INTEGER DEFAULT 0,created REAL,updated REAL);
            CREATE TABLE IF NOT EXISTS scenes(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),title TEXT NOT NULL,position INTEGER,revision INTEGER NOT NULL,revision_id TEXT NOT NULL,body TEXT NOT NULL,selected_image_id TEXT,selected_video_id TEXT,created REAL,updated REAL);
            CREATE TABLE IF NOT EXISTS scene_revisions(id TEXT PRIMARY KEY,scene_id TEXT REFERENCES scenes(id),number INTEGER,body TEXT,created REAL,UNIQUE(scene_id,number));
            CREATE TABLE IF NOT EXISTS sessions(hash TEXT PRIMARY KEY,origin TEXT,label TEXT,expires REAL,created REAL);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),scene_id TEXT,kind TEXT,status TEXT NOT NULL,snapshot TEXT NOT NULL,dependencies TEXT NOT NULL,priority INTEGER DEFAULT 0,request_key TEXT UNIQUE,comfy_prompt_id TEXT,progress REAL DEFAULT 0,error TEXT,attempt INTEGER DEFAULT 1,created REAL,started REAL,finished REAL);
            CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,project_id TEXT REFERENCES projects(id),scene_id TEXT,job_id TEXT,source_asset_id TEXT,kind TEXT,path TEXT,sha256 TEXT,metadata TEXT,approved INTEGER DEFAULT 0,approval_source TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS timelines(project_id TEXT PRIMARY KEY REFERENCES projects(id),revision INTEGER,body TEXT,updated REAL);
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,kind TEXT,data TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS workflow_registry(id TEXT PRIMARY KEY,body TEXT NOT NULL,updated REAL);
            CREATE TABLE IF NOT EXISTS chat(id TEXT PRIMARY KEY,project_id TEXT,role TEXT,content TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS qa(id TEXT PRIMARY KEY,asset_id TEXT,model TEXT,body TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS asset_selections(scene_id TEXT,kind TEXT,asset_id TEXT,input_signature TEXT,PRIMARY KEY(scene_id,kind));
            CREATE INDEX IF NOT EXISTS scenes_project ON scenes(project_id,position);
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,priority,created);
            CREATE INDEX IF NOT EXISTS jobs_scene_kind ON jobs(scene_id,kind);
            CREATE INDEX IF NOT EXISTS assets_project ON assets(project_id,created);
            CREATE INDEX IF NOT EXISTS assets_scene ON assets(scene_id,created);
            CREATE INDEX IF NOT EXISTS qa_asset ON qa(asset_id,created);
            INSERT OR IGNORE INTO migrations VALUES(1,strftime('%s','now'));
            ''')
            if 'cancel_requested' not in {row[1] for row in con.execute('PRAGMA table_info(jobs)')}:
                con.execute('ALTER TABLE jobs ADD COLUMN cancel_requested INTEGER DEFAULT 0')

    def all(self, sql, args=()):
        with self.connect() as con:
            return [dict(row) for row in con.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.all(sql, args)
        return rows[0] if rows else None

    def execute(self, sql, args=()):
        with self.connect(True) as con:
            return con.execute(sql, args).rowcount

    def event(self, kind, data):
        self.execute('INSERT INTO events(kind,data,created) VALUES(?,?,?)', (kind, encode(data), now()))
        from .desktop import notice
        notice(kind, data)

    def projects(self):
        rows = self.all('SELECT * FROM projects WHERE archived=0 ORDER BY updated DESC')
        for row in rows:
            row['settings'] = json.loads(row['settings'])
            row['scene_count'] = self.one('SELECT COUNT(*) n FROM scenes WHERE project_id=?', (row['id'],))['n']
        return rows

    def create_project(self, title, brief='', mode='hybrid', settings=None):
        identifier = uid()
        shape=(settings or {}).get('video_shape','landscape')
        if shape not in ['landscape','portrait','square']:raise ValueError('Choose a supported video shape.')
        export_width,export_height={'landscape':(1920,1080),'portrait':(1080,1920),'square':(1080,1080)}[shape]
        values = {'image_workflow': 'qwen-image-21', 'video_workflow': 'wan22-i2v', 'llm': '', 'qa_model': '', 'qa_enabled': False, 'audio_mode': 'silent', 'width': 640, 'height': 352, 'frames': 49, 'fps': 16, 'image_steps': 12, 'candidates': 1, 'max_retries': 2, 'gates': {'storyboard': False, 'prompts': False, 'image': True, 'video': True, 'timeline': True}, 'paused': True, 'auto_export': False, **(settings or {})}
        values.setdefault('auto_approve_images',True)
        values.setdefault('auto_approve_videos',True)
        values['auto_export']=(settings or {}).get('auto_export',True)
        self.execute('INSERT INTO projects(id,title,brief,mode,settings,created,updated) VALUES(?,?,?,?,?,?,?)', (identifier, title, brief, mode, encode(values), now(), now()))
        self.execute('INSERT INTO timelines VALUES(?,?,?,?)', (identifier, 1, encode({'clips': [], 'audio': [], 'settings': {'width': export_width, 'height': export_height, 'fps': 30, 'codec': 'h264', 'crf': 18, 'audio_mode': 'silent', 'fit': 'pad', 'transition': 'cut', 'loop': 'none', 'repeats': 1}}), now()))
        self.event('project.created', {'project_id': identifier})
        return self.project(identifier)

    def project(self, identifier):
        row = self.one('SELECT * FROM projects WHERE id=?', (identifier,))
        if not row:
            raise KeyError('Project not found')
        row['settings'] = json.loads(row['settings'])
        row['scenes'] = self.scenes(identifier)
        timeline = self.one('SELECT * FROM timelines WHERE project_id=?', (identifier,))
        row['timeline'] = {**json.loads(timeline['body']), 'revision': timeline['revision']} if timeline else None
        return row

    def update_project(self, identifier, revision, values):
        with self.connect(True) as con:
            row = con.execute('SELECT * FROM projects WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise KeyError('Project not found')
            if row['revision'] != revision:
                raise Conflict('This project changed in another view. Refresh before saving.')
            config = {**json.loads(row['settings']), **values.get('settings', {})}
            con.execute('UPDATE projects SET title=?,brief=?,mode=?,settings=?,revision=revision+1,updated=? WHERE id=?', (values.get('title', row['title']), values.get('brief', row['brief']), values.get('mode', row['mode']), encode(config), now(), identifier))
        self.event('project.updated', {'project_id': identifier})
        return self.project(identifier)

    def scenes(self, project_id):
        rows = self.all('SELECT * FROM scenes WHERE project_id=? ORDER BY position,created', (project_id,))
        assets=self.assets(project_id=project_id)
        grouped={}
        for asset in assets:grouped.setdefault(asset['scene_id'],[]).append(asset)
        for row in rows:
            row['body'] = json.loads(row['body'])
            row['assets'] = grouped.get(row['id'],[])
        return rows

    def scene(self, identifier):
        row = self.one('SELECT * FROM scenes WHERE id=?', (identifier,))
        if not row:
            raise KeyError('Scene not found')
        row['body'] = json.loads(row['body'])
        row['assets'] = self.assets(identifier)
        return row

    def add_scene(self, project_id, title, body=None):
        self.project(project_id)
        identifier, revision_id = uid(), uid()
        data = {'summary': '', 'image_prompt': '', 'video_prompt': '', 'negative_prompt': '', 'duration': 3, 'seed': 26102026, 'image_workflow': None, 'video_workflow': None, 'notes': '', 'locked': False, **(body or {})}
        position = self.one('SELECT COALESCE(MAX(position),-1)+1 n FROM scenes WHERE project_id=?', (project_id,))['n']
        with self.connect(True) as con:
            con.execute('INSERT INTO scenes(id,project_id,title,position,revision,revision_id,body,created,updated) VALUES(?,?,?,?,?,?,?,?,?)', (identifier, project_id, title, position, 1, revision_id, encode(data), now(), now()))
            con.execute('INSERT INTO scene_revisions VALUES(?,?,?,?,?)', (revision_id, identifier, 1, encode({'title': title, **data}), now()))
        self.event('scene.created', {'project_id': project_id, 'scene_id': identifier})
        return self.scene(identifier)

    def update_scene(self, identifier, revision, title=None, body=None):
        revision_id = uid()
        with self.connect(True) as con:
            row = con.execute('SELECT * FROM scenes WHERE id=?', (identifier,)).fetchone()
            if not row:
                raise KeyError('Scene not found')
            if row['revision'] != revision:
                raise Conflict('This scene has a newer revision. Refresh to keep both changes safe.')
            data = {**json.loads(row['body']), **(body or {})}
            new_title = title if title is not None else row['title']
            con.execute('UPDATE scenes SET title=?,revision=revision+1,revision_id=?,body=?,updated=? WHERE id=?', (new_title, revision_id, encode(data), now(), identifier))
            con.execute('INSERT INTO scene_revisions VALUES(?,?,?,?,?)', (revision_id, identifier, revision+1, encode({'title': new_title, **data}), now()))
        self.event('scene.updated', {'project_id': row['project_id'], 'scene_id': identifier, 'revision': revision+1})
        return self.scene(identifier)

    def assets(self, scene_id=None, project_id=None):
        if scene_id:
            rows = self.all('SELECT * FROM assets WHERE scene_id=? ORDER BY created DESC', (scene_id,))
        elif project_id:
            rows = self.all('SELECT * FROM assets WHERE project_id=? ORDER BY created DESC', (project_id,))
        else:
            rows = self.all('SELECT * FROM assets ORDER BY created DESC LIMIT 100')
        for row in rows:
            row['metadata'] = json.loads(row['metadata'])
            row.pop('path', None)
        return rows

    def jobs(self, project_id=None):
        rows = self.all('SELECT * FROM jobs' + (' WHERE project_id=?' if project_id else '') + ' ORDER BY created DESC', (project_id,) if project_id else ())
        for row in rows:
            row['snapshot'] = json.loads(row['snapshot'])
            row['dependencies'] = json.loads(row['dependencies'])
        return rows


db = Store()
