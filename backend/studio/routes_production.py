import json
from pathlib import Path

from fastapi import APIRouter,Depends,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field

from .adapters import registry
from .config import ROOT
from .exports import queue_export,rebuild_timeline,save_timeline
from .media import add_asset,asset_path,select_asset
from .production import ACTIVE,approve_and_continue,pause,produce,queue_snapshot,state,supersede_pending,update_job
from .security import require_session,ticket,verify_ticket
from .store import db,now,uid

router=APIRouter(prefix='/api')


class ProductionInput(BaseModel):
    scope:str=Field(default='all',pattern='^(all|stills|videos|selected_still|selected_video)$')
    scene_id:str|None=None


@router.get('/workflows')
async def workflows(session=Depends(require_session)):
    return registry.list()


@router.post('/workflows/discover')
async def discover(session=Depends(require_session)):
    try:
        return await registry.discover()
    except Exception:
        raise HTTPException(503,'ComfyUI is unavailable. Start the existing backend and try discovery again.')


@router.post('/projects/{identifier}/produce')
async def production(identifier:str,body:ProductionInput,session=Depends(require_session)):
    if not registry.list():
        await registry.discover()
    return produce(identifier,body.scope,body.scene_id)


@router.post('/projects/{identifier}/pause')
async def pause_project(identifier:str,session=Depends(require_session)):
    return pause(identifier,True)


@router.post('/projects/{identifier}/resume')
async def resume_project(identifier:str,session=Depends(require_session)):
    return pause(identifier,False)


@router.post('/jobs/{identifier}/retry')
async def retry(identifier:str,values:dict|None=None,session=Depends(require_session)):
    job=db.one('SELECT * FROM jobs WHERE id=?',(identifier,))
    if not job:
        raise KeyError('Job not found')
    if job['status']=='needs_attention' and not (values or {}).get('confirm_uncertain'):
        raise HTTPException(409,'The original submission is uncertain. Review backend queue/history and explicitly confirm before retrying.')
    if job['status'] not in ['failed','cancelled','needs_attention']:
        raise HTTPException(409,'Only failed, cancelled, or explicitly reviewed uncertain jobs can be retried.')
    pause(job['project_id'],False)
    return queue_snapshot(job['kind'],json.loads(job['snapshot']),force=True,priority=30)


@router.post('/jobs/{identifier}/cancel')
async def cancel(identifier:str,session=Depends(require_session)):
    job=db.one('SELECT * FROM jobs WHERE id=?',(identifier,))
    if not job:
        raise KeyError('Job not found')
    if job['status']!='queued':
        raise HTTPException(409,'This action removes pending work only. An active render keeps its immutable inputs.')
    update_job(identifier,'cancelled',finished=now())
    return {'cancelled':True}


@router.post('/jobs/{identifier}/priority')
async def prioritize(identifier:str,values:dict,session=Depends(require_session)):
    priority=int(values.get('priority',0))
    if not -100<=priority<=100:
        raise HTTPException(422,'Use a priority from -100 to 100.')
    db.execute("UPDATE jobs SET priority=? WHERE id=? AND status='queued'",(priority,identifier))
    return {'priority':priority}


@router.post('/assets/{identifier}/select')
async def select(identifier:str,session=Depends(require_session)):
    result=select_asset(identifier)
    asset=db.one('SELECT scene_id FROM assets WHERE id=?',(identifier,))
    supersede_pending(asset['scene_id'])
    return result


@router.post('/assets/{identifier}/approve')
async def approve(identifier:str,session=Depends(require_session)):
    return approve_and_continue(identifier)


@router.post('/assets/{identifier}/ticket')
async def media_ticket(identifier:str,session=Depends(require_session)):
    asset_path(identifier)
    value=ticket(session,'media',identifier,ttl=180)
    return {'url':f'/api/media/{identifier}?ticket={value}','expires_in':180}


@router.get('/media/{identifier}')
async def media(identifier:str,request:Request,ticket:str=''):
    verify_ticket(ticket,'media',identifier,origin=request.headers.get('origin'))
    return FileResponse(asset_path(identifier),filename=None,headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer'})


@router.post('/scenes/{identifier}/import')
async def import_still(identifier:str,file:UploadFile,session=Depends(require_session)):
    scene=db.scene(identifier)
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ['.png','.jpg','.jpeg','.webp']:
        raise HTTPException(422,'Import a PNG, JPEG, or WebP still image.')
    temporary=ROOT/'temp'/(uid()+suffix)
    total=0
    try:
        with temporary.open('wb') as output:
            while chunk:=await file.read(1024*1024):
                total+=len(chunk)
                if total>50*1024*1024:
                    raise HTTPException(413,'The still exceeds the 50 MB import limit.')
                output.write(chunk)
        import asyncio
        asset=await asyncio.to_thread(add_asset,scene['project_id'],identifier,None,'image',temporary,None,{'provenance':'user_import','original_name':Path(file.filename).name})
        select_asset(asset['id'],True)
        return {'asset_id':asset['id']}
    finally:
        temporary.unlink(missing_ok=True)


@router.post('/projects/{identifier}/timeline/rebuild')
async def rebuild(identifier:str,values:dict|None=None,session=Depends(require_session)):
    return rebuild_timeline(identifier,partial=bool((values or {}).get('partial',False)))


@router.patch('/projects/{identifier}/timeline')
async def timeline(identifier:str,values:dict,session=Depends(require_session)):
    return save_timeline(identifier,int(values['revision']),values['clips'],values.get('audio',[]),values['settings'])


@router.post('/projects/{identifier}/export')
async def export(identifier:str,session=Depends(require_session)):
    job=queue_export(identifier)
    return {'job_id':job['id']}
