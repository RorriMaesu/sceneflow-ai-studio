"""Shows and films contain bounded sequence projects; legacy projects retain their IDs."""
import json
import httpx
from fastapi import APIRouter,Depends
from pydantic import BaseModel,ConfigDict,Field
from .security import require_session
from .store import db,uid,now,encode,Conflict

router=APIRouter(prefix='/api')

def migrate(store=None):
    with (store or db).connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS productions(id TEXT PRIMARY KEY,title TEXT,purpose TEXT,brief TEXT,canon TEXT,revision INTEGER,root_project_id TEXT UNIQUE,created REAL,updated REAL);
        CREATE TABLE IF NOT EXISTS production_episodes(id TEXT PRIMARY KEY,production_id TEXT,season INTEGER,number INTEGER,title TEXT,summary TEXT,start_state TEXT,end_state TEXT,revision INTEGER,UNIQUE(production_id,season,number));
        CREATE TABLE IF NOT EXISTS production_sequences(id TEXT PRIMARY KEY,episode_id TEXT,project_id TEXT UNIQUE,position INTEGER,title TEXT,UNIQUE(episode_id,position));
        CREATE TABLE IF NOT EXISTS production_outlines(id TEXT PRIMARY KEY,production_id TEXT,job_id TEXT,base_revision INTEGER,season INTEGER,body TEXT,status TEXT,created REAL);
        ''')

def list_productions():
    migrate()
    return db.all('SELECT p.*,COUNT(e.id) episode_count FROM productions p LEFT JOIN production_episodes e ON e.production_id=p.id GROUP BY p.id ORDER BY p.updated DESC')

def get(identifier):
    migrate()
    row=db.one('SELECT * FROM productions WHERE id=?',(identifier,))
    if not row:raise KeyError('Production not found')
    row['episodes']=db.all('SELECT * FROM production_episodes WHERE production_id=? ORDER BY season,number',(identifier,))
    sequences=db.all('SELECT s.* FROM production_sequences s JOIN production_episodes e ON e.id=s.episode_id WHERE e.production_id=? ORDER BY s.position',(identifier,))
    for episode in row['episodes']:
        episode['sequences']=[s for s in sequences if s['episode_id']==episode['id']]
    row['outlines']=[{**p,'body':json.loads(p['body'])} for p in db.all("SELECT * FROM production_outlines WHERE production_id=? AND status='pending' ORDER BY created DESC",(identifier,))]
    return row

def membership(project_id,store=None):
    store=store or db
    if not store.one("SELECT name FROM sqlite_master WHERE type='table' AND name='production_sequences'"):return None
    return store.one('SELECT p.id production_id,p.root_project_id,p.title production_title,p.purpose,p.canon,p.revision canon_revision,e.*,s.position sequence_position,s.title sequence_title FROM production_sequences s JOIN production_episodes e ON e.id=s.episode_id JOIN productions p ON p.id=e.production_id WHERE s.project_id=?',(project_id,))

def cast_scope(project_id,store=None):
    member=membership(project_id,store)
    return member['root_project_id'] if member else project_id

def _project(con,production,title,summary):
    identifier=uid()
    original=con.execute('SELECT settings FROM projects WHERE id=?',(production['root_project_id'],)).fetchone()
    values={**json.loads(original['settings']),'production_root':False,'paused':True,'auto_export':False}
    con.execute('INSERT INTO projects(id,title,brief,mode,settings,created,updated) VALUES(?,?,?,?,?,?,?)',(identifier,title,summary,'hybrid',encode(values),now(),now()))
    con.execute('INSERT INTO timelines VALUES(?,?,?,?)',(identifier,1,encode({'clips':[],'audio':[],'settings':{'width':1920,'height':1080,'fps':30,'codec':'h264','crf':18,'audio_mode':'silent','fit':'pad','transition':'cut','loop':'none','repeats':1}}),now()))
    return identifier

def _episode(con,production,season,number,title,summary,start_state='',end_state=''):
    identifier=uid()
    con.execute('INSERT INTO production_episodes VALUES(?,?,?,?,?,?,?,?,?)',(identifier,production['id'],season,number,title,summary,start_state,end_state,1))
    project_id=_project(con,production,production['title']+' · '+title+' · Sequence 1',summary)
    con.execute('INSERT INTO production_sequences VALUES(?,?,?,?,?)',(uid(),identifier,project_id,1,'Sequence 1'))
    return identifier

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class NewProduction(Strict):
    title:str=Field(min_length=1,max_length=160)
    purpose:str=Field(pattern='^(series|movie|music_video)$')
    brief:str=Field(default='',max_length=12000)
class Canon(Strict):
    revision:int
    canon:str=Field(max_length=12000)
class Episode(Strict):
    season:int=Field(default=1,ge=1,le=100)
    number:int=Field(ge=1,le=10000)
    title:str=Field(min_length=1,max_length=160)
    summary:str=Field(default='',max_length=4000)
    start_state:str=Field(default='',max_length=2000)
    end_state:str=Field(default='',max_length=2000)
class Sequence(Strict):
    title:str=Field(min_length=1,max_length=160)
class EpisodeEdit(Strict):
    revision:int
    title:str=Field(min_length=1,max_length=160)
    summary:str=Field(default='',max_length=4000)
    start_state:str=Field(default='',max_length=2000)
    end_state:str=Field(default='',max_length=2000)
class OutlineRequest(Strict):
    model:str=Field(min_length=1,max_length=200)
    count:int=Field(default=6,ge=1,le=24)
    season:int=Field(default=1,ge=1,le=100)
class PlannedEpisode(Strict):
    title:str=Field(min_length=1,max_length=160)
    summary:str=Field(max_length=600)
    start_state:str=Field(max_length=400)
    end_state:str=Field(max_length=400)
class Outline(Strict):
    episodes:list[PlannedEpisode]=Field(min_length=1,max_length=24)

@router.get('/productions')
async def listing(session=Depends(require_session)):return list_productions()
@router.get('/productions/{identifier}')
async def detail(identifier:str,session=Depends(require_session)):return get(identifier)
@router.get('/projects/{identifier}/production')
async def current(identifier:str,session=Depends(require_session)):
    db.project(identifier)
    member=membership(identifier)
    return {'membership':member,'production':get(member['production_id']) if member else None}
@router.post('/productions')
async def create(body:NewProduction,session=Depends(require_session)):
    migrate()
    root=db.create_project(body.title,body.brief,'manual',{'production_root':True,'production_purpose':body.purpose,'auto_export':False})
    identifier=uid()
    with db.connect(True) as con:
        con.execute('UPDATE projects SET archived=1 WHERE id=?',(root['id'],))
        con.execute('INSERT INTO productions VALUES(?,?,?,?,?,?,?,?,?)',(identifier,body.title,body.purpose,body.brief,'',1,root['id'],now(),now()))
        if body.purpose=='music_video':_episode(con,{'id':identifier,'title':body.title,'root_project_id':root['id']},1,1,'Main video',body.brief)
    return get(identifier)
@router.patch('/productions/{identifier}/canon')
async def canon(identifier:str,body:Canon,session=Depends(require_session)):
    get(identifier)
    with db.connect(True) as con:
        cursor=con.execute('UPDATE productions SET canon=?,revision=revision+1,updated=? WHERE id=? AND revision=?',(body.canon,now(),identifier,body.revision))
        if cursor.rowcount!=1:raise Conflict('The shared story guide changed. Refresh before saving.')
    return get(identifier)
@router.post('/productions/{identifier}/episodes')
async def episode(identifier:str,body:Episode,session=Depends(require_session)):
    production=get(identifier)
    with db.connect(True) as con:
        if con.execute('SELECT id FROM production_episodes WHERE production_id=? AND season=? AND number=?',(identifier,body.season,body.number)).fetchone():raise ValueError('That episode number is already in use.')
        _episode(con,production,**body.model_dump())
        con.execute('UPDATE productions SET revision=revision+1,updated=? WHERE id=?',(now(),identifier))
    return get(identifier)
@router.post('/productions/{identifier}/episodes/{episode_id}/sequences')
async def sequence(identifier:str,episode_id:str,body:Sequence,session=Depends(require_session)):
    production=get(identifier)
    with db.connect(True) as con:
        item=con.execute('SELECT * FROM production_episodes WHERE id=? AND production_id=?',(episode_id,identifier)).fetchone()
        if not item:raise ValueError('Choose an episode in this production.')
        position=con.execute('SELECT COALESCE(MAX(position),0)+1 FROM production_sequences WHERE episode_id=?',(episode_id,)).fetchone()[0]
        project_id=_project(con,production,production['title']+' · '+item['title']+' · '+body.title,item['summary'])
        con.execute('INSERT INTO production_sequences VALUES(?,?,?,?,?)',(uid(),episode_id,project_id,position,body.title))
        con.execute('UPDATE productions SET revision=revision+1,updated=? WHERE id=?',(now(),identifier))
    return get(identifier)

@router.patch('/productions/{identifier}/episodes/{episode_id}')
async def edit_episode(identifier:str,episode_id:str,body:EpisodeEdit,session=Depends(require_session)):
    get(identifier)
    with db.connect(True) as con:
        changed=con.execute('UPDATE production_episodes SET title=?,summary=?,start_state=?,end_state=?,revision=revision+1 WHERE id=? AND production_id=? AND revision=?',(body.title,body.summary,body.start_state,body.end_state,episode_id,identifier,body.revision))
        if changed.rowcount!=1:raise Conflict('This episode changed. Refresh before saving.')
        con.execute('UPDATE productions SET revision=revision+1,updated=? WHERE id=?',(now(),identifier))
    db.event('production.updated',{'production_id':identifier})
    return db.one('SELECT * FROM production_episodes WHERE id=?',(episode_id,))
@router.post('/productions/{identifier}/outline')
async def outline(identifier:str,body:OutlineRequest,session=Depends(require_session)):
    from .director import model_details
    from .production import queue_snapshot
    production=get(identifier)
    await model_details(body.model)
    job=queue_snapshot('outline',{'project_id':production['root_project_id'],'production_id':identifier,'base_revision':production['revision'],'title':production['title'],'brief':production['brief'],'canon':production['canon'],**body.model_dump(),'manual_override':True,'manual_requested_at':now()})
    return {'job_id':job['id']}
@router.post('/productions/{identifier}/outlines/{proposal_id}/apply')
async def apply(identifier:str,proposal_id:str,session=Depends(require_session)):
    production=get(identifier)
    with db.connect(True) as con:
        proposal=con.execute("SELECT * FROM production_outlines WHERE id=? AND production_id=? AND status='pending'",(proposal_id,identifier)).fetchone()
        revision=con.execute('SELECT revision FROM productions WHERE id=?',(identifier,)).fetchone()[0]
        if not proposal or proposal['base_revision']!=revision:raise Conflict('This production changed. Request and review a fresh outline.')
        if con.execute('SELECT id FROM production_episodes WHERE production_id=? AND season=?',(identifier,proposal['season'])).fetchone():raise ValueError('This season already has episodes. Use a new season or add episodes individually.')
        plan=Outline.model_validate_json(proposal['body'])
        for number,item in enumerate(plan.episodes,1):_episode(con,production,proposal['season'],number,**item.model_dump())
        con.execute("UPDATE production_outlines SET status='applied' WHERE id=?",(proposal_id,))
        con.execute('UPDATE productions SET revision=revision+1,updated=? WHERE id=?',(now(),identifier))
    return get(identifier)

async def execute_outline(job,snapshot):
    from .director import prepare_gpu,structured,unload
    from .production import update_job
    production=get(snapshot['production_id'])
    if job['project_id']!=production['root_project_id']:raise ValueError('The outline belongs to a different production.')
    async with httpx.AsyncClient(timeout=30) as client:
        if reason:=await prepare_gpu(client,snapshot['model']):
            update_job(job['id'],'queued',error=reason);return
        update_job(job['id'],'running',started=now(),error=None)
        try:
            result=await structured(client,snapshot['model'],[{'role':'system','content':'Plan a complete connected season or film chapter outline. Return exactly the requested episode count. Use concise summaries with clear start/end character states. Respect the shared story guide. Do not generate footage or claim installed tools.'},{'role':'user','content':encode({k:snapshot[k] for k in ['title','brief','canon','count']})}],Outline,{'num_predict':6000})
            if len(result.episodes)!=snapshot['count']:raise ValueError('The outline did not contain the requested number of episodes. No episodes were added.')
            db.execute('INSERT INTO production_outlines VALUES(?,?,?,?,?,?,?,?)',(uid(),production['id'],job['id'],snapshot['base_revision'],snapshot['season'],encode(result.model_dump()),'pending',now()))
        finally:await unload(client,snapshot['model'])
    update_job(job['id'],'completed',progress=1,finished=now())
