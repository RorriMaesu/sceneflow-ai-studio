"""Owned visual references and reversible, reference-guided corrections."""
import asyncio
import hashlib
import json
from pathlib import Path

from fastapi import APIRouter,Depends,UploadFile
from pydantic import BaseModel,ConfigDict,Field
from PIL import Image

from .config import ROOT
from .media import add_asset,asset_path
from .security import require_session
from .store import db,uid

router=APIRouter(prefix='/api')


def visual_inputs(scene,project,kind):
    body=scene['body'];config=project['settings']
    references=body.get('reference_asset_ids',config.get('reference_asset_ids',[])) if kind=='image' else []
    if not isinstance(references,list) or len(references)>3 or len(set(references))!=len(references) or any(not isinstance(v,str) for v in references):
        raise ValueError('Choose up to three different project reference images.')
    prompt=body.get('image_prompt' if kind=='image' else 'video_prompt','')
    rules=config.get('visual_rules','').strip()
    if rules:prompt+='\nLocked appearance and style rules: '+rules
    workflow=body.get(kind+'_workflow') or config.get(kind+'_workflow')
    if references and workflow=='qwen-image-21':workflow='qwen-image-21-reference'
    if kind=='video' and body.get('ending_asset_id') and workflow=='wan22-i2v':workflow='wan22-first-last'
    return prompt,workflow,references


def owned_references(store,project_id,identifiers):
    if not isinstance(identifiers,list) or len(identifiers)>3 or any(not isinstance(v,str) for v in identifiers) or len(set(identifiers))!=len(identifiers):raise ValueError('Choose up to three different project reference images.')
    result=[]
    for identifier in identifiers:
        row=store.one("SELECT * FROM assets WHERE id=? AND project_id=? AND kind='image'",(identifier,project_id))
        if not row or json.loads(row['metadata']).get('role')=='edit_mask':raise ValueError('A reference must be an image owned by this project.')
        result.append({'id':row['id'],'sha256':row['sha256']})
    return result


@router.post('/projects/{identifier}/references/import')
async def import_reference(identifier:str,file:UploadFile,session=Depends(require_session)):
    db.project(identifier)
    suffix=Path(file.filename or '').suffix.lower()
    if suffix not in ['.png','.jpg','.jpeg','.webp']:raise ValueError('Choose a PNG, JPEG or WebP reference.')
    from .routes_editing import receive
    path=await receive(file,suffix,50*1024**2)
    try:
        asset=await asyncio.to_thread(add_asset,identifier,None,None,'image',path,None,{'role':'visual_reference','original_name':Path(file.filename).name,'provenance':'user_import'})
        return {'asset_id':asset['id']}
    finally:path.unlink(missing_ok=True)


class Correction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    prompt:str=Field(min_length=5,max_length=6000)
    mask_asset_id:str|None=None
    seed:int=Field(default=26102026,ge=0,lt=2**63)
    steps:int=Field(default=25,ge=1,le=60)
    strength:float=Field(default=.6,ge=.1,le=1)


@router.post('/assets/{identifier}/mask')
async def import_mask(identifier:str,file:UploadFile,session=Depends(require_session)):
    source=db.one("SELECT * FROM assets WHERE id=? AND kind='image' AND scene_id IS NOT NULL",(identifier,))
    if not source:raise ValueError('Choose a scene still to correct.')
    from .routes_editing import receive
    path=await receive(file,'.png',20*1024**2)
    try:
        with Image.open(path) as mask:
            if mask.format!='PNG' or mask.size!=(json.loads(source['metadata'])['width'],json.loads(source['metadata'])['height']):raise ValueError('The PNG mask must match the exact source image size.')
            gray=mask.convert('L')
            if gray.getextrema()[1]==0:raise ValueError('Paint the area you want to change first.')
            gray.convert('RGB').save(path)
        asset=await asyncio.to_thread(add_asset,source['project_id'],None,None,'image',path,None,{'role':'edit_mask','mask_for':identifier})
        return {'asset_id':asset['id']}
    finally:path.unlink(missing_ok=True)


@router.post('/assets/{identifier}/correct')
async def correct(identifier:str,body:Correction,session=Depends(require_session)):
    from .adapters import registry
    from .production import pause,queue_snapshot,snapshot_for
    source=db.one("SELECT * FROM assets WHERE id=? AND kind='image' AND scene_id IS NOT NULL",(identifier,))
    if not source:raise ValueError('Choose a scene still to correct.')
    scene=db.scene(source['scene_id']);project=db.project(source['project_id']);meta=json.loads(source['metadata'])
    with Image.open(asset_path(identifier)) as image:
        if image.convert('RGBA').getchannel('A').getextrema()!=(255,255):raise ValueError('Correction currently requires an opaque still. Flatten transparency before importing it.')
    if meta['width']%32 or meta['height']%32 or max(meta['width'],meta['height'])>2048:raise ValueError('Correction currently supports still dimensions divisible by 32, up to 2048 pixels. Generate a compatible still first.')
    refs=owned_references(db,project['id'],[identifier])
    for ref in project['settings'].get('reference_asset_ids',[]):
        if ref!=identifier and len(refs)<3:refs+=owned_references(db,project['id'],[ref])
    mask=None
    if body.mask_asset_id:
        mask=db.one("SELECT * FROM assets WHERE id=? AND project_id=?",(body.mask_asset_id,project['id']))
        if not mask or json.loads(mask['metadata']).get('mask_for')!=identifier:raise ValueError('The mask belongs to a different image.')
    if not registry.info:await registry.discover()
    config={**project['settings'],'width':meta['width'],'height':meta['height'],'image_steps':body.steps}
    edited={**scene,'body':{**scene['body'],'image_workflow':'qwen-image-21-reference','image_prompt':body.prompt,'reference_asset_ids':[r['id'] for r in refs],'seed':body.seed}}
    snap=snapshot_for(edited,project,'image',config=config)
    snap.update(reference_assets=refs,reference_asset_ids=[r['id'] for r in refs],source_asset_id=identifier,source_sha256=source['sha256'],edit_operation=True,edit_strength=body.strength,mask_asset_id=mask['id'] if mask else None,mask_sha256=mask['sha256'] if mask else None)
    snap['manual_override']=True
    return queue_snapshot('image',snap,force=True,priority=30)


@router.get('/projects/{identifier}/exports')
async def project_exports(identifier:str,page:int=1,session=Depends(require_session)):
    db.project(identifier)
    if not 1<=page<=100000:raise ValueError('Choose a valid export history page.')
    rows=db.all("SELECT * FROM assets WHERE project_id=? AND kind='export' ORDER BY created DESC,id DESC LIMIT 21 OFFSET ?",(identifier,(page-1)*20))
    for row in rows:row['metadata']=json.loads(row['metadata']);row.pop('path',None)
    return {'items':rows[:20],'page':page,'has_more':len(rows)>20,'total':db.one("SELECT COUNT(*) n FROM assets WHERE project_id=? AND kind='export'",(identifier,))['n']}


@router.get('/assets/{identifier}/review-frames')
async def review_frames(identifier:str,session=Depends(require_session)):
    from .quality import samples
    asset=db.one("SELECT * FROM assets WHERE id=? AND kind IN ('image','video')",(identifier,))
    if not asset:raise ValueError('Choose a scene still or video.')
    path=asset_path(identifier)
    with path.open('rb') as file:
        if hashlib.file_digest(file,'sha256').hexdigest()!=asset['sha256']:raise ValueError('This media changed on disk.')
    frames,technical=await asyncio.to_thread(samples,asset)
    return {'frames':frames,'technical':technical}
