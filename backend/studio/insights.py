"""Observed timings and bounded, local waveform analysis."""
import asyncio
import hashlib
import json
import statistics
import wave
from array import array
from pathlib import Path

from fastapi import APIRouter,Depends

from .config import ROOT
from .media import asset_path,executable,run_tool
from .security import require_session
from .store import db,uid

router=APIRouter(prefix='/api')


def performance(store,project_id):
    groups={}
    for job in store.all("SELECT kind,snapshot,started,finished FROM jobs WHERE status='completed' AND kind IN ('image','video') AND started IS NOT NULL AND finished>started"):
        s=json.loads(job['snapshot'])
        if s.get('edit_operation'):continue
        key=(job['kind'],s.get('workflow_id'),s.get('width'),s.get('height'),s.get('image_steps') if job['kind']=='image' else s.get('frames'))
        groups.setdefault(key,[]).append(job['finished']-job['started'])
    rows=[]
    for key,values in groups.items():
        kind,workflow,width,height,count=key
        rows.append({'kind':kind,'workflow':workflow,'width':width,'height':height,'steps' if kind=='image' else 'frames':count,'samples':len(values),'median_seconds':round(statistics.median(values),1),'min_seconds':round(min(values),1),'max_seconds':round(max(values),1)})
    ranges=[];unknown=0
    for job in store.all("SELECT kind,snapshot FROM jobs WHERE project_id=? AND status='queued' AND kind IN ('image','video')",(project_id,)):
        s=json.loads(job['snapshot']);key=(job['kind'],s.get('workflow_id'),s.get('width'),s.get('height'),s.get('image_steps') if job['kind']=='image' else s.get('frames'))
        if key in groups:ranges.append((min(groups[key]),max(groups[key])))
        else:unknown+=1
    return {'presets':rows,'queued_observed_range_seconds':[round(sum(v[0] for v in ranges)),round(sum(v[1] for v in ranges))] if ranges else None,'unknown_jobs':unknown,'note':'Measured job elapsed time includes loading and collection. Estimates exclude active jobs, unmeasured presets, AI reviews, pauses and external work. Hardware load and restarts can change timing.'}


@router.get('/projects/{identifier}/performance')
async def performance_report(identifier:str,session=Depends(require_session)):
    db.project(identifier)
    from .production import state
    return {**performance(db,identifier),'production':state(identifier),'run':db.one('SELECT * FROM production_runs WHERE project_id=?',(identifier,))}


def waveform(asset):
    path=asset_path(asset['id'])
    with path.open('rb') as file:
        if hashlib.file_digest(file,'sha256').hexdigest()!=asset['sha256']:raise ValueError('Audio source changed on disk.')
    from .storage import role_folder,cache_file
    folder=role_folder('cache')/'waveforms';folder.mkdir(parents=True,exist_ok=True);cache=folder/(asset['sha256']+'.json')
    if cache.is_file():return json.loads(cache.read_text())
    target=cache_file('waveform-'+uid()+'.wav')
    try:
        run_tool([executable('ffmpeg'),'-y','-v','error','-i',str(path),'-t','600','-vn','-ac','1','-ar','8000','-c:a','pcm_s16le',str(target)])
        with wave.open(str(target),'rb') as audio:
            samples=array('h',audio.readframes(audio.getnframes()));duration=audio.getnframes()/audio.getframerate()
        stride=max(1,(len(samples)+255)//256);peaks=[round(max(abs(min(samples[i:i+stride])),abs(max(samples[i:i+stride])))/32768,4) for i in range(0,len(samples),stride)]
        result={'peaks':peaks,'duration':duration,'truncated':json.loads(asset['metadata']).get('duration',duration)>600,'source_sha256':asset['sha256']}
        temporary=cache.with_suffix('.'+uid()+'.part');temporary.write_text(json.dumps(result));temporary.replace(cache)
        return result
    finally:target.unlink(missing_ok=True)


@router.get('/assets/{identifier}/waveform')
async def audio_waveform(identifier:str,session=Depends(require_session)):
    asset=db.one("SELECT * FROM assets WHERE id=? AND kind IN ('audio','video')",(identifier,))
    if not asset:raise ValueError('Choose an audio track or video with sound.')
    return await asyncio.to_thread(waveform,asset)
