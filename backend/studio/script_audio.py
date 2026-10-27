"""Versioned scripts and sound takes; edits never overwrite an earlier recording."""
import json
from .store import db, uid, now, encode, Conflict


def migrate(store=None):
    with (store or db).connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS cast_members(id TEXT PRIMARY KEY,project_id TEXT,name TEXT,voice TEXT,language TEXT,revision INTEGER,created REAL);
        CREATE TABLE IF NOT EXISTS script_lines(id TEXT PRIMARY KEY,project_id TEXT,scene_id TEXT,cast_id TEXT,text TEXT,start REAL,revision INTEGER,selected_asset_id TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS script_line_revisions(id TEXT,revision INTEGER,body TEXT,created REAL,PRIMARY KEY(id,revision));
        CREATE TABLE IF NOT EXISTS sound_takes(job_id TEXT PRIMARY KEY,project_id TEXT,line_id TEXT,line_revision INTEGER,asset_id TEXT,body TEXT,created REAL);
        ''')
        if 'auto_timing' not in {r[1] for r in con.execute('PRAGMA table_info(script_lines)')}:con.execute('ALTER TABLE script_lines ADD COLUMN auto_timing INTEGER DEFAULT 1')


def view(project_id):
    migrate();db.project(project_id)
    return {'cast':db.all('SELECT * FROM cast_members WHERE project_id=? ORDER BY created',(project_id,)),
            'lines':db.all('SELECT * FROM script_lines WHERE project_id=? ORDER BY created',(project_id,)),
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
        start=values.get('start')
        con.execute('INSERT OR REPLACE INTO script_lines VALUES(?,?,?,?,?,?,?,?,?,?)',(identifier,project_id,values.get('scene_id'),values.get('cast_id'),values['text'],start if start is not None else 0,next_revision,None,previous['created'] if previous else now(),int(start is None)))
    return db.one('SELECT * FROM script_lines WHERE id=?',(identifier,))


def queue_line(project_id,identifier,automatic=False):
    from .audio_engine import queue_sound
    migrate()
    row=db.one('SELECT * FROM script_lines WHERE id=? AND project_id=?',(identifier,project_id))
    if not row:raise KeyError('Script line not found')
    cast=db.one('SELECT * FROM cast_members WHERE id=? AND project_id=?',(row['cast_id'],project_id)) if row['cast_id'] else None
    takes=db.one('SELECT COUNT(*) n FROM sound_takes WHERE line_id=?',(identifier,))['n']
    return queue_sound(project_id,'voices-small',{'text':row['text'],'voice':cast['voice'] if cast else 'Ryan','language':cast['language'] if cast else 'English',
                       'line_id':identifier,'line_revision':row['revision'],'cast_revision':cast['revision'] if cast else None,'seed':26102026+takes},row['scene_id'],automatic=automatic)


def apply_take(job,snapshot,asset):
    migrate();inputs=snapshot['inputs'];identifier=inputs.get('line_id')
    db.execute('INSERT OR IGNORE INTO sound_takes VALUES(?,?,?,?,?,?,?)',(job['id'],job['project_id'],identifier,inputs.get('line_revision'),asset['id'],encode(inputs),now()))
    if identifier:
        # A later script edit keeps the old take but does not select it for the new wording.
        db.execute('UPDATE script_lines SET selected_asset_id=? WHERE id=? AND project_id=? AND revision=?',(asset['id'],identifier,job['project_id'],inputs['line_revision']))
        retime(job['project_id'])


def retime(project_id):
    cursor=0
    for line in db.all('SELECT * FROM script_lines WHERE project_id=? ORDER BY created',(project_id,)):
        if line['auto_timing']:db.execute('UPDATE script_lines SET start=? WHERE id=?',(cursor,line['id']))
        start=cursor if line['auto_timing'] else line['start']
        asset=db.one('SELECT metadata FROM assets WHERE id=? AND project_id=?',(line['selected_asset_id'],project_id)) if line['selected_asset_id'] else None
        cursor=start+(json.loads(asset['metadata'])['duration'] if asset else 0)+.25


def place(project_id,asset_id,start=0):
    from .exports import save_timeline
    project=db.project(project_id)
    row=db.one("SELECT * FROM assets WHERE id=? AND project_id=? AND kind='audio'",(asset_id,project_id))
    if not row:raise ValueError('Choose a sound from this production.')
    metadata=json.loads(row['metadata']);timeline=project['timeline']
    if not timeline['clips']:raise ValueError('Add pictures or video to the edit first, then place your sound.')
    track={'id':uid(),'asset_id':asset_id,'start':start,'trim_in':0,'trim_out':metadata['duration'],'role':metadata.get('role','voiceover'),'volume':1,'fade_in':0,'fade_out':0,'mute':False,'duck':metadata.get('role')=='music'}
    return save_timeline(project_id,timeline['revision'],timeline['clips'],[*timeline.get('audio',[]),track],{**timeline['settings'],'audio_mode':'mixed'})


def queue_missing(project_id,automatic=False):
    from .audio_engine import pack_ready
    current=view(project_id)
    lines=[line for line in current['lines'] if not line['selected_asset_id']]
    if lines and not pack_ready('voices-small'):raise ValueError('Finish the voice sample in Setup before making this script.')
    jobs=[]
    for line in lines:jobs.append(queue_line(project_id,line['id'],automatic)['job_id'])
    return {'jobs':jobs,'planned':len(jobs),'reason':'Preset speech is selected for saved dialogue. Each line uses its character’s saved voice; earlier takes remain available.'}


def place_script(project_id):
    from .exports import save_timeline
    retime(project_id)
    lines=view(project_id)['lines'];project=db.project(project_id);timeline=project['timeline']
    if not lines or any(not l['selected_asset_id'] for l in lines):raise ValueError('Create speech for every current script line before placing the whole conversation.')
    if not timeline['clips']:raise ValueError('Add pictures or video to the edit first.')
    ids={l['id'] for l in lines}
    tracks=[t for t in timeline.get('audio',[]) if t.get('script_line_id') not in ids]
    for line in lines:
        asset=db.one("SELECT * FROM assets WHERE id=? AND project_id=? AND kind='audio'",(line['selected_asset_id'],project_id))
        if not asset:raise ValueError('A speech take is missing. Recreate that line before placing the conversation.')
        tracks.append({'id':uid(),'asset_id':asset['id'],'start':line['start'],'trim_in':0,'trim_out':json.loads(asset['metadata'])['duration'],'role':'voiceover','volume':1,'fade_in':0,'fade_out':0,'mute':False,'script_line_id':line['id']})
    return save_timeline(project_id,timeline['revision'],timeline['clips'],tracks,{**timeline['settings'],'audio_mode':'mixed'})


def bundle_snapshot(con,project_id):
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='script_lines'").fetchone():return None
    scope=project_id
    if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='production_sequences'").fetchone():
        member=con.execute('SELECT p.root_project_id FROM production_sequences s JOIN production_episodes e ON e.id=s.episode_id JOIN productions p ON p.id=e.production_id WHERE s.project_id=?',(project_id,)).fetchone()
        if member:scope=member[0]
    return {'cast':[dict(r) for r in con.execute('SELECT * FROM cast_members WHERE project_id=?',(scope,))],
            'lines':[dict(r) for r in con.execute('SELECT * FROM script_lines WHERE project_id=?',(project_id,))],
            'revisions':[dict(r) for r in con.execute('SELECT * FROM script_line_revisions WHERE id IN (SELECT id FROM script_lines WHERE project_id=?)',(project_id,))],
            'takes':[dict(r) for r in con.execute('SELECT * FROM sound_takes WHERE project_id=?',(project_id,))]}


def prepare_snapshot(value,mapping,scene_ids,asset_ids,job_ids):
    if value is None:return
    if not isinstance(value,dict) or set(value)!={'cast','lines','revisions','takes'} or any(not isinstance(v,list) or len(v)>10000 for v in value.values()):raise ValueError('Unsupported bundled script data.')
    cast_ids={r['id'] for r in value['cast']};line_ids={r['id'] for r in value['lines']}
    for identifier in [r['id'] for r in value['cast']+value['lines']]:
        if identifier in mapping:raise ValueError('Duplicate bundled script identifier.')
        mapping[identifier]=uid()
    for row in value['lines']:
        if row.get('cast_id') and row['cast_id'] not in cast_ids or row.get('scene_id') and row['scene_id'] not in scene_ids or row.get('selected_asset_id') and row['selected_asset_id'] not in asset_ids:raise ValueError('Bundled script references another production.')
        if not isinstance(row['text'],str) or len(row['text'])>600:raise ValueError('Unsupported bundled script line.')
    for row in value['takes']:
        if row['job_id'] not in job_ids or row['asset_id'] not in asset_ids or row.get('line_id') and row['line_id'] not in line_ids:raise ValueError('Bundled sound history references missing media or jobs.')
    for row in value['revisions']:
        if row['id'] not in line_ids:raise ValueError('Bundled script history has no matching line.')


def restore_snapshot(con,value,mapping,project_id,insert,remap):
    if value is None:return
    for key,table in [('cast','cast_members'),('lines','script_lines'),('revisions','script_line_revisions'),('takes','sound_takes')]:
        for old in value[key]:
            row=remap(old,mapping)
            if 'project_id' in row:row['project_id']=project_id
            if 'body' in row:row['body']=encode(remap(json.loads(row['body']),mapping))
            insert(table,row)
