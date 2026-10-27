import asyncio
from fastapi import APIRouter,Depends
from pydantic import BaseModel,ConfigDict,Field
from .security import require_session
from .store import db
from . import script_audio,audio_engine

router=APIRouter(prefix='/api')
class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Cast(Strict):
    name:str=Field(min_length=1,max_length=100)
    voice:str='Ryan'
    language:str='English'
class Line(Strict):
    text:str=Field(min_length=1,max_length=600)
    scene_id:str|None=None
    cast_id:str|None=None
    start:float=Field(default=0,ge=0,le=36000,allow_inf_nan=False)
class EditLine(Line):
    revision:int
class Place(Strict):
    asset_id:str
    start:float=Field(default=0,ge=0,le=36000,allow_inf_nan=False)
class Cue(Strict):
    kind:str=Field(pattern='^(music|effects)$')
    prompt:str=Field(min_length=1,max_length=2000)
    seconds:float=Field(ge=1,le=60,allow_inf_nan=False)
    lyrics:str=Field(default='',max_length=6000)
    instrumental:bool=True
    seed:int=Field(default=26102026,ge=0,lt=2**63)
    scene_id:str|None=None

@router.get('/projects/{project_id}/sound')
async def view(project_id:str,session=Depends(require_session)):
    return {**script_audio.view(project_id),'voices':audio_engine.VOICES,'languages':audio_engine.LANGUAGES,
            'tools':{key:{'ready':audio_engine.pack_ready(key),'tested_seconds':(audio_engine.qualification(key) or {}).get('body',{}).get('tested_seconds')} for key in ['voices-small','music','effects']}}
@router.post('/projects/{project_id}/cast')
async def cast(project_id:str,body:Cast,session=Depends(require_session)):
    return script_audio.add_cast(project_id,**body.model_dump())
@router.post('/projects/{project_id}/lines')
async def line(project_id:str,body:Line,session=Depends(require_session)):
    return script_audio.save_line(project_id,body.model_dump())
@router.patch('/projects/{project_id}/lines/{identifier}')
async def edit_line(project_id:str,identifier:str,body:EditLine,session=Depends(require_session)):
    return script_audio.save_line(project_id,body.model_dump(exclude={'revision'}),identifier,body.revision)
@router.post('/projects/{project_id}/lines/{identifier}/speak')
async def speak(project_id:str,identifier:str,session=Depends(require_session)):
    return await asyncio.to_thread(script_audio.queue_line,project_id,identifier)
@router.post('/projects/{project_id}/sound/place')
async def place(project_id:str,body:Place,session=Depends(require_session)):
    return script_audio.place(project_id,body.asset_id,body.start)
@router.post('/projects/{project_id}/sound/cues')
async def cue(project_id:str,body:Cue,session=Depends(require_session)):
    db.project(project_id)
    return await asyncio.to_thread(audio_engine.queue_sound,project_id,body.kind,body.model_dump(exclude={'kind','scene_id'}),body.scene_id)
