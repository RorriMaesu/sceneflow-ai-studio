import asyncio
import json
from pathlib import Path

from fastapi import APIRouter,Depends,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field

from .adapters import graph_hash,registry,validate_graph
from .bundles import create_bundle,restore_bundle
from .config import ROOT
from .exports import save_timeline
from .media import add_asset,select_asset
from .production import pause,supersede_pending
from .security import require_session,ticket,verify_ticket
from .store import db,encode,now,uid

router=APIRouter(prefix='/api')


async def receive(file,suffix,limit):
    path=ROOT/'temp'/(uid()+suffix);total=0
    try:
        with path.open('wb') as out:
            while data:=await file.read(1024*1024):
                total+=len(data)
                if total>limit:raise HTTPException(413,'This file exceeds the supported import size.')
                out.write(data)
    except BaseException:
        path.unlink(missing_ok=True);raise
    return path


@router.post('/projects/{identifier}/import-media')
async def import_media(identifier:str,file:UploadFile,scene_id:str|None=None,session=Depends(require_session)):
    db.project(identifier)
    if scene_id and db.scene(scene_id)['project_id']!=identifier:raise ValueError('Scene and project do not match.')
    suffix=Path(file.filename or '').suffix.lower()
    kind='video' if suffix in ['.mp4','.webm','.mkv','.mov'] else 'audio' if suffix in ['.wav','.mp3','.flac','.ogg','.m4a'] else None
    if not kind:raise ValueError('Import a standard video or audio file.')
    if kind=='video' and not scene_id:raise ValueError('Select a scene for imported video.')
    path=await receive(file,suffix,2*1024**3)
    try:
        asset=await asyncio.to_thread(add_asset,identifier,scene_id,None,kind,path,None,{'provenance':'user_import','original_name':Path(file.filename).name})
        if kind=='video':select_asset(asset['id'],True)
        return {'asset_id':asset['id']}
    finally:path.unlink(missing_ok=True)


@router.get('/projects/{identifier}/timeline/history')
async def timeline_history(identifier:str,session=Depends(require_session)):
    db.project(identifier)
    db.execute('CREATE TABLE IF NOT EXISTS timeline_revisions(project_id TEXT,revision INTEGER,body TEXT,created REAL,PRIMARY KEY(project_id,revision))')
    rows=db.all('SELECT * FROM timeline_revisions WHERE project_id=? ORDER BY revision DESC',(identifier,))
    return [{**r,'body':json.loads(r['body'])} for r in rows]


@router.post('/projects/{identifier}/timeline/restore/{revision}')
async def restore_timeline(identifier:str,revision:int,session=Depends(require_session)):
    row=db.one('SELECT * FROM timeline_revisions WHERE project_id=? AND revision=?',(identifier,revision))
    if not row:raise KeyError('Timeline revision not found')
    value=json.loads(row['body']);current=db.project(identifier)['timeline']
    return save_timeline(identifier,current['revision'],value['clips'],value['audio'],value['settings'])


@router.post('/scenes/{identifier}/restore/{revision}')
async def restore_scene(identifier:str,revision:int,session=Depends(require_session)):
    row=db.one('SELECT * FROM scene_revisions WHERE scene_id=? AND number=?',(identifier,revision))
    if not row:raise KeyError('Scene revision not found')
    body=json.loads(row['body']);title=body.pop('title');current=db.scene(identifier)
    result=db.update_scene(identifier,current['revision'],title,body);supersede_pending(identifier)
    return result


@router.post('/scenes/{identifier}/duplicate')
async def duplicate_scene(identifier:str,session=Depends(require_session)):
    scene=db.scene(identifier)
    return db.add_scene(scene['project_id'],scene['title']+' · Copy',scene['body'])


@router.post('/projects/{identifier}/backup')
async def backup(identifier:str,session=Depends(require_session)):
    return await asyncio.to_thread(create_bundle,identifier)


@router.get('/backups')
async def backups(session=Depends(require_session)):
    return [{'id':p.name.split('.')[0],'filename':p.name,'bytes':p.stat().st_size,'created':p.stat().st_mtime} for p in sorted((ROOT/'backups').glob('*.sceneflow.zip'),key=lambda p:p.stat().st_mtime,reverse=True)]


@router.post('/backups/{identifier}/ticket')
async def backup_ticket(identifier:str,session=Depends(require_session)):
    from uuid import UUID
    identifier=str(UUID(identifier));path=ROOT/'backups'/(identifier+'.sceneflow.zip')
    if not path.is_file():raise KeyError('Backup not found')
    value=ticket(session,'backup',identifier,ttl=300)
    return {'url':f'/api/backups/{identifier}/download?ticket={value}'}


@router.get('/backups/{identifier}/download')
async def download_backup(identifier:str,request:Request,ticket:str=''):
    from uuid import UUID
    identifier=str(UUID(identifier));verify_ticket(ticket,'backup',identifier,origin=request.headers.get('origin'))
    return FileResponse(ROOT/'backups'/(identifier+'.sceneflow.zip'),filename='SceneFlow-project-'+identifier+'.zip')


@router.post('/backups/restore')
async def restore(file:UploadFile,session=Depends(require_session)):
    path=await receive(file,'.zip',10*1024**3)
    try:return await asyncio.to_thread(restore_bundle,path)
    finally:path.unlink(missing_ok=True)


class WorkflowInput(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=160)
    family:str=Field(min_length=1,max_length=100)
    task:str=Field(pattern='^(text_to_image|image_to_video)$')
    graph:dict
    mappings:dict
    output_nodes:list[str]=Field(min_length=1,max_length=5)
    constraints:dict=Field(default_factory=lambda:{'multiple':16,'max_width':832,'max_height':480,'max_frames':81,'frames_multiple':4,'frames_offset':1})


def validate_mappings(body):
    if len(encode(body.graph))>2*1024**2:raise ValueError('The workflow exceeds 2 MB.')
    allowed={'positive_prompt','negative_prompt','seed','width','height','frames','fps','source_image','output_prefix','image_steps'}
    required={'positive_prompt','seed','width','height'}|({'source_image','frames','fps'} if body.task=='image_to_video' else set())
    if set(body.mappings)-allowed or required-set(body.mappings):raise ValueError('Map prompt, seed and dimensions, plus source still, frames and fps for video.')
    for mappings in body.mappings.values():
        for target in mappings if isinstance(mappings,list) else [mappings]:
            if not isinstance(target,dict) or set(target)!={'node','input'} or target['node'] not in body.graph or target['input'] not in body.graph[target['node']].get('inputs',{}):
                raise ValueError('A mapping must identify an existing workflow node input.')
    c=body.constraints
    for key in ['multiple','max_width','max_height','max_frames','frames_multiple','frames_offset']:
        if key in c and (not isinstance(c[key],int) or not 0<=c[key]<=4096):raise ValueError('Workflow limits must be bounded integers.')
    if c.get('multiple',0)<1 or c.get('frames_multiple',1)<1 or not 64<=c.get('max_width',0)<=2048 or not 64<=c.get('max_height',0)<=2048 or c.get('max_frames',81)>241:
        raise ValueError('Use conservative bounded dimensions and frame counts for this computer.')


@router.post('/workflows/import')
async def import_workflow(body:WorkflowInput,session=Depends(require_session)):
    validate_mappings(body)
    if not registry.info:await registry.discover()
    reasons=validate_graph(body.graph,registry.info,body.output_nodes)
    identifier=uid();entry={'id':identifier,**body.model_dump(),'workflow_hash':graph_hash(body.graph),'imported':True,'tested':False,'capabilities':{'source_image':body.task=='image_to_video','audio':any(n.get('class_type')=='SaveAudio' for n in body.graph.values())},'status':'ready' if not reasons else 'unavailable','reasons':reasons}
    db.execute('INSERT INTO workflow_registry VALUES(?,?,?)',(identifier,encode(entry),now()))
    db.event('workflow.imported',{'workflow_id':identifier})
    return entry
