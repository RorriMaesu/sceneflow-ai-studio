import json

from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field

from .director import apply_proposal,context,llm_models,migrate
from .production import pause,produce,queue_snapshot
from .security import require_session
from .store import db,encode,now,uid

router=APIRouter(prefix='/api')


class RequestAI(BaseModel):
    model_config=ConfigDict(extra='forbid')
    model:str=Field(min_length=1,max_length=200)
    message:str=Field(default='',max_length=6000)
    scene_count:int=Field(default=4,ge=1,le=40)
    scene_id:str|None=None
    auto_apply:bool=False
    auto_continue:bool=False
    allow_operations:bool=False


@router.get('/language-models')
async def language_models(session=Depends(require_session)):
    try:
        return await llm_models()
    except Exception:
        raise HTTPException(503,'Ollama is unavailable. Start the local service and refresh the model list.')


def queue_ai(identifier,body,kind):
    migrate();project=db.project(identifier)
    if body.scene_id and body.scene_id not in [s['id'] for s in project['scenes']]:
        raise ValueError('The selected scene belongs to another project.')
    if kind=='director' and not body.message.strip():
        raise ValueError('Write a message for your Director.')
    if body.auto_apply and (project['scenes'] or project['mode']!='automatic'):
        raise ValueError('Automatic plan application is limited to an empty project in Automatic mode.')
    snapshot={'project_id':identifier,'context':context(project,body.scene_id),'base_revision':project['revision'],'scene_revisions':{s['id']:s['revision'] for s in project['scenes']},**body.model_dump()}
    if kind=='director':
        snapshot['recent']=list(reversed(db.all('SELECT role,content FROM chat WHERE project_id=? ORDER BY created DESC LIMIT 4',(identifier,))))
        db.execute('INSERT INTO chat VALUES(?,?,?,?,?)',(uid(),identifier,'user',body.message,now()))
    snapshot.update(manual_override=True,manual_requested_at=now())
    job=queue_snapshot(kind,snapshot,force=True,priority=40)
    return {'job_id':job['id']}


@router.post('/projects/{identifier}/plan')
async def plan(identifier:str,body:RequestAI,session=Depends(require_session)):
    return queue_ai(identifier,body,'plan')


@router.post('/projects/{identifier}/director')
async def director(identifier:str,body:RequestAI,session=Depends(require_session)):
    return queue_ai(identifier,body,'director')


@router.get('/projects/{identifier}/director')
async def history(identifier:str,session=Depends(require_session)):
    db.project(identifier);migrate()
    proposals=db.all('SELECT * FROM proposals WHERE project_id=? ORDER BY created DESC LIMIT 30',(identifier,))
    for item in proposals:
        item['body']=json.loads(item['body']);item['scene_revisions']=json.loads(item['scene_revisions'])
        from .director import impact
        item['impact']=impact(item)
    return {'chat':db.all('SELECT * FROM chat WHERE project_id=? ORDER BY created LIMIT 500',(identifier,)),'proposals':proposals,'commands':db.all('SELECT * FROM director_commands WHERE project_id=? ORDER BY created DESC LIMIT 30',(identifier,))}


@router.post('/proposals/{identifier}/apply')
async def apply(identifier:str,session=Depends(require_session)):
    return apply_proposal(identifier)


@router.post('/proposals/{identifier}/dismiss')
async def dismiss(identifier:str,session=Depends(require_session)):
    db.execute("UPDATE proposals SET status='dismissed' WHERE id=? AND status='pending'",(identifier,))
    return {'dismissed':True}


@router.post('/projects/{identifier}/approve-planning')
async def approve_planning(identifier:str,session=Depends(require_session)):
    project=db.project(identifier)
    db.update_project(identifier,project['revision'],{'settings':{'planning_approved':{s['id']:s['revision_id'] for s in project['scenes']}}})
    db.execute("UPDATE jobs SET status='queued',error=NULL WHERE project_id=? AND status='awaiting_review'",(identifier,))
    return {'approved':True}
