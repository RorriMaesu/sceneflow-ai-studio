import json
import httpx
from pathlib import Path

from fastapi import APIRouter,Depends,HTTPException,Request,UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field

from .adapters import registry
from .config import ROOT,settings
from .exports import queue_export,rebuild_timeline,save_timeline
from .media import add_asset,asset_path,select_asset
from .production import ACTIVE,approve_and_continue,pause,produce,queue_snapshot,state,supersede_pending,update_job
from .security import require_session,ticket,verify_ticket
from .store import db,encode,now,uid

router=APIRouter(prefix='/api')


class ProductionInput(BaseModel):
    scope:str=Field(default='all',pattern='^(all|stills|videos|selected_still|selected_video|missing_stills|missing_videos)$')
    scene_id:str|None=None
    scene_ids:list[str]|None=Field(default=None,max_length=200)


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
    from .production import Dispatcher
    dispatcher=Dispatcher()
    if body.scope=='all':await dispatcher.reuse_completed(identifier)
    result=produce(identifier,body.scope,body.scene_id,body.scene_ids)
    if body.scope=='all':await dispatcher.maybe_export(identifier)
    return result


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
    frozen=json.loads(job['snapshot']);frozen.update(manual_override=True,manual_requested_at=now())
    return queue_snapshot(job['kind'],frozen,force=True,priority=30)


@router.post('/jobs/{identifier}/cancel')
async def cancel(identifier:str,session=Depends(require_session)):
    job=db.one('SELECT * FROM jobs WHERE id=?',(identifier,))
    if not job:
        raise KeyError('Job not found')
    if job['status'] in ['queued','awaiting_review']:
        update_job(identifier,'cancelled',finished=now())
        return {'cancelled':True}
    if job['status'] not in ACTIVE or job['kind'] not in ['image','video'] or not job['comfy_prompt_id']:
        raise HTTPException(409,'This job cannot be cancelled from its current state.')
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response=await client.get(settings['comfy_url']+'/queue');response.raise_for_status();queue=response.json()
            owned=any(item[1]==job['comfy_prompt_id'] and len(item)>3 and item[3].get('sceneflow',{}).get('job_id')==identifier for item in queue.get('queue_running',[])+queue.get('queue_pending',[]))
            if not owned:raise HTTPException(409,'No matching active Studio-owned prompt was found. Refresh its state before cancelling.')
            db.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?',(identifier,))
            # This backend endpoint atomically targets one exact prompt. Never use global interrupt.
            response=await client.post(settings['comfy_url']+'/api/jobs/'+job['comfy_prompt_id']+'/cancel');response.raise_for_status()
            if not response.json().get('cancelled'):
                db.execute('UPDATE jobs SET cancel_requested=0 WHERE id=?',(identifier,))
                return {'cancelled':False,'detail':'The job finished before cancellation.'}
            db.execute('UPDATE jobs SET error=? WHERE id=?',('Cancellation requested for this Studio-owned prompt.',identifier))
            return {'cancelled':True}
    except httpx.HTTPError:
        raise HTTPException(503,'Targeted cancellation could not be confirmed. Studio will keep checking the original job and will not issue a global interrupt.')


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
    asset=db.one('SELECT * FROM assets WHERE id=?',(identifier,))
    supersede_pending(asset['scene_id'])
    project=db.project(asset['project_id'])
    if asset['kind']=='image' and project['settings'].get('qa_enabled') and project['settings'].get('qa_auto',True) and project['settings'].get('qa_image_mode')=='selected':
        from .quality import queue_review
        try:await queue_review(identifier,automatic=bool(state(project['id'])['auto_run']) and project['mode']!='manual')
        except Exception as error:
            metadata=json.loads(asset['metadata']);metadata['qa_error']='Visual review is unavailable: '+str(error)[:300]+'. You can approve this asset manually.'
            db.execute('UPDATE assets SET metadata=? WHERE id=?',(encode(metadata),identifier))
    return result


@router.post('/assets/{identifier}/approve')
async def approve(identifier:str,session=Depends(require_session)):
    result=approve_and_continue(identifier)
    from .production import Dispatcher
    asset=db.one('SELECT project_id,kind FROM assets WHERE id=?',(identifier,))
    if asset['kind']=='video':await Dispatcher().maybe_export(asset['project_id'])
    return result


@router.post('/assets/{identifier}/ticket')
async def media_ticket(identifier:str,session=Depends(require_session)):
    asset_path(identifier)
    value=ticket(session,'media',identifier,ttl=1800)
    return {'url':f'/api/media/{identifier}?ticket={value}','expires_in':1800}


def export_asset(identifier):
    asset=db.one("SELECT * FROM assets WHERE id=? AND kind='export'",(identifier,))
    if not asset:raise ValueError('Choose a saved video from this project.')
    return asset,asset_path(identifier)


@router.post('/assets/{identifier}/download-ticket')
async def download_ticket(identifier:str,session=Depends(require_session)):
    asset,path=export_asset(identifier)
    value=ticket(session,'download',identifier,ttl=1800)
    return {'url':f'/api/downloads/{identifier}?ticket={value}'}


@router.get('/downloads/{identifier}')
async def download_video(identifier:str,request:Request,ticket:str=''):
    import re
    verify_ticket(ticket,'download',identifier,origin=request.headers.get('origin'))
    asset,path=export_asset(identifier);title=db.project(asset['project_id'])['title']
    name='SceneFlow-'+re.sub(r'[<>:"/\\|?*\x00-\x1f]','',title)[:80].strip(' .')+'-'+identifier[:8]+path.suffix
    return FileResponse(path,filename=name,media_type='video/mp4',headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer'})


@router.post('/assets/{identifier}/reveal')
async def reveal_video(identifier:str,session=Depends(require_session)):
    import os,subprocess
    asset,path=export_asset(identifier)
    if os.name!='nt':raise ValueError('Show in folder is available in the local Windows studio. Download the MP4 instead.')
    subprocess.Popen(['explorer.exe','/select,',str(path)],creationflags=0x08000000)
    return {'shown':True}


@router.get('/media/{identifier}')
async def media(identifier:str,request:Request,ticket:str='',thumbnail:bool=False):
    verify_ticket(ticket,'media',identifier,origin=request.headers.get('origin'))
    path=asset_path(identifier)
    if thumbnail:
        candidate=path.with_suffix('.thumbnail.jpg').resolve()
        from .storage import reject_links
        if candidate.parent==path.parent and candidate.is_file():path=reject_links(candidate)
    return FileResponse(path,filename=None,headers={'Cache-Control':'private, no-store','Referrer-Policy':'no-referrer'})


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


@router.post('/projects/{identifier}/preview')
async def editing_preview(identifier:str,session=Depends(require_session)):
    job=queue_export(identifier,preview=True)
    return {'job_id':job['id']}
