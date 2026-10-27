"""Versioned scripts and sound takes; edits never overwrite an earlier recording."""
import json
from .store import db, uid, now, encode, Conflict


def migrate():
    with db.connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS cast_members(id TEXT PRIMARY KEY,project_id TEXT,name TEXT,voice TEXT,language TEXT,revision INTEGER,created REAL);
        CREATE TABLE IF NOT EXISTS script_lines(id TEXT PRIMARY KEY,project_id TEXT,scene_id TEXT,cast_id TEXT,text TEXT,start REAL,revision INTEGER,selected_asset_id TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS script_line_revisions(id TEXT,revision INTEGER,body TEXT,created REAL,PRIMARY KEY(id,revision));
        CREATE TABLE IF NOT EXISTS sound_takes(job_id TEXT PRIMARY KEY,project_id TEXT,line_id TEXT,line_revision INTEGER,asset_id TEXT,body TEXT,created REAL);
        ''')


def view(project_id):
    migrate();db.project(project_id)
    return {'cast':db.all('SELECT * FROM cast_members WHERE project_id=? ORDER BY created',(project_id,)),
            'lines':db.all('SELECT * FROM script_lines WHERE project_id=? ORDER BY start,created',(project_id,)),
            'takes':[{**r,'body':json.loads(r['body'])} for r in db.all('SELECT * FROM sound_takes WHERE project_id=? ORDER BY created DESC',(project_id,))]}


def add_cast(project_id,name,voice='Ryan',language='English'):
    from .audio_engine import VOICES,LANGUAGES
    migrate();db.project(project_id)
    if voice not in VOICES or language not in LANGUAGES:raise ValueError('Choose an available voice and language.')
    identifier=uid()
    db.execute('INSERT INTO cast_members VALUES(?,?,?,?,?,?,?)',(identifier,project_id,name,voice,language,1,now()))
    return db.one('SELECT * FROM cast_members WHERE id=?',(identifier,))


def save_line(project_id,values,identifier=None,revision=None):
    migrate();db.project(project_id)
    if values.get('scene_id') and db.scene(values['scene_id'])['project_id']!=project_id:raise ValueError('Choose a scene in this production.')
    if values.get('cast_id') and not db.one('SELECT id FROM cast_members WHERE id=? AND project_id=?',(values['cast_id'],project_id)):raise ValueError('Choose a character in this production.')
    identifier=identifier or uid()
    with db.connect(True) as con:
        previous=con.execute('SELECT * FROM script_lines WHERE id=? AND project_id=?',(identifier,project_id)).fetchone()
        if revision is not None and (not previous or previous['revision']!=revision):raise Conflict('This line changed in another view. Refresh before saving.')
        next_revision=previous['revision']+1 if previous else 1
        if previous:con.execute('INSERT OR IGNORE INTO script_line_revisions VALUES(?,?,?,?)',(identifier,previous['revision'],encode(dict(previous)),now()))
        con.execute('INSERT OR REPLACE INTO script_lines VALUES(?,?,?,?,?,?,?,?,?)',(identifier,project_id,values.get('scene_id'),values.get('cast_id'),values['text'],values.get('start',0),next_revision,None,previous['created'] if previous else now()))
    return db.one('SELECT * FROM script_lines WHERE id=?',(identifier,))


def queue_line(project_id,identifier,automatic=False):
    from .audio_engine import queue_sound
    migrate()
    row=db.one('SELECT * FROM script_lines WHERE id=? AND project_id=?',(identifier,project_id))
    if not row:raise KeyError('Script line not found')
    cast=db.one('SELECT * FROM cast_members WHERE id=? AND project_id=?',(row['cast_id'],project_id)) if row['cast_id'] else None
    return queue_sound(project_id,'voices-small',{'text':row['text'],'voice':cast['voice'] if cast else 'Ryan','language':cast['language'] if cast else 'English',
                       'line_id':identifier,'line_revision':row['revision'],'cast_revision':cast['revision'] if cast else None,'seed':26102026},row['scene_id'],automatic=automatic)


def apply_take(job,snapshot,asset):
    migrate();inputs=snapshot['inputs'];identifier=inputs.get('line_id')
    db.execute('INSERT OR IGNORE INTO sound_takes VALUES(?,?,?,?,?,?,?)',(job['id'],job['project_id'],identifier,inputs.get('line_revision'),asset['id'],encode(inputs),now()))
    if identifier:
        # A later script edit keeps the old take but does not select it for the new wording.
        db.execute('UPDATE script_lines SET selected_asset_id=? WHERE id=? AND project_id=? AND revision=?',(asset['id'],identifier,job['project_id'],inputs['line_revision']))


def place(project_id,asset_id,start=0):
    from .exports import save_timeline
    project=db.project(project_id)
    row=db.one("SELECT * FROM assets WHERE id=? AND project_id=? AND kind='audio'",(asset_id,project_id))
    if not row:raise ValueError('Choose a sound from this production.')
    metadata=json.loads(row['metadata']);timeline=project['timeline']
    if not timeline['clips']:raise ValueError('Add pictures or video to the edit first, then place your sound.')
    track={'id':uid(),'asset_id':asset_id,'start':start,'trim_in':0,'trim_out':metadata['duration'],'role':metadata.get('role','voiceover'),'volume':1,'fade_in':0,'fade_out':0,'mute':False}
    return save_timeline(project_id,timeline['revision'],timeline['clips'],[*timeline.get('audio',[]),track],{**timeline['settings'],'audio_mode':'mixed'})
