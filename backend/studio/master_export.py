"""Reviewable episode/film assembly from current, verified sequence exports."""
import asyncio,copy,json
from fastapi import APIRouter,Depends
from pydantic import BaseModel,ConfigDict,Field
from .store import db,now,uid
from .security import require_session
from . import productions,music_planning

router=APIRouter(prefix='/api/productions')


def current_export(project):
    subs=music_planning.captions(project['id'],db)
    expected=subs['revision'] if subs['source'].get('include_mp4') and subs['items'] else 0
    for asset in db.all("SELECT * FROM assets WHERE project_id=? AND kind='export' ORDER BY created DESC",(project['id'],)):
        meta=json.loads(asset['metadata'])
        if not meta.get('partial') and not meta.get('is_editing_preview') and meta.get('timeline_revision')==project['timeline']['revision'] and meta.get('caption_revision',0)==expected:
            return {**asset,'metadata':meta}
    return None


def review(identifier):
    production=productions.get(identifier);episodes=[]
    for episode in production['episodes']:
        sequences=[]
        for sequence in episode['sequences']:
            project=db.project(sequence['project_id']);asset=current_export(project)
            sequences.append({**sequence,'ready':bool(asset),'seconds':asset['metadata']['duration'] if asset else None,'asset_id':asset['id'] if asset else None,'timeline_revision':project['timeline']['revision']})
        episodes.append({**episode,'sequences':sequences,'ready':bool(sequences) and all(s['ready'] for s in sequences)})
    exports=[{**r,'metadata':json.loads(r['metadata'])} for r in db.all("SELECT * FROM assets WHERE project_id=? AND kind='export' ORDER BY created DESC LIMIT 20",(production['root_project_id'],))]
    return {'revision':production['revision'],'episodes':episodes,'exports':exports,'music_master':production['purpose']=='music_video'}


def queue(identifier,revision,episode_ids):
    from .production import queue_snapshot
    production=productions.get(identifier)
    if production['revision']!=revision:raise ValueError('The production changed. Refresh this review before assembling it.')
    if not episode_ids or len(set(episode_ids))!=len(episode_ids):raise ValueError('Choose episodes or chapters once, in their story order.')
    selected=[e for e in production['episodes'] if e['id'] in episode_ids]
    if {e['id'] for e in selected}!=set(episode_ids):raise ValueError('Choose episodes from this production.')
    clips=[];audio=[];captions=[];frozen=[];elapsed=0;settings=None
    music=production['purpose']=='music_video'
    for episode in selected:
        if not episode['sequences']:raise ValueError('Every selected chapter needs at least one finished sequence.')
        for sequence in episode['sequences']:
            project=db.project(sequence['project_id']);asset=current_export(project)
            if not asset:raise ValueError('Save a current finished video for '+project['title']+' before assembling the production.')
            config=project['timeline']['settings']
            settings=settings or {**config,'transition':'cut','loop':'none','repeats':1,'audio_mode':'mixed' if music else 'preserve'}
            span=round(asset['metadata'].get('frames',round(asset['metadata']['duration']*asset['metadata'].get('fps',settings['fps'])))/asset['metadata'].get('fps',settings['fps'])*settings['fps'])/settings['fps']
            frozen.append({'project_id':project['id'],'asset_id':asset['id'],'sha256':asset['sha256'],'timeline_revision':project['timeline']['revision'],'start':elapsed,'seconds':span})
            clips.append({'id':uid(),'scene_id':None,'asset_id':asset['id'],'source_sha256':asset['sha256'],'trim_in':0,'trim_out':span,'speed':1,'volume':1,'mute':music,'transition':'cut'})
            if music:
                if config.get('loop','none')!='none' or config.get('repeats',1)!=1:raise ValueError('Use each music-video sequence once, without a loop, before assembling it around the locked song.')
                for clip in project['timeline']['clips']:
                    original=db.one('SELECT metadata FROM assets WHERE id=?',(clip['asset_id'],))
                    if config.get('audio_mode')!='silent' and not clip.get('mute') and (json.loads(original['metadata']).get('audio_streams') or clip.get('audio_asset_id')):raise ValueError('Mute original clip sound in music-video sequences before master assembly. Speech and effects tracks are retained separately.')
                if config.get('audio_mode')=='mixed':
                    for track in project['timeline'].get('audio',[]):
                        if track.get('role')=='music':continue
                        source=db.one('SELECT sha256 FROM assets WHERE id=? AND project_id=?',(track['asset_id'],project['id']))
                        if not source:raise ValueError('A sequence sound track is missing.')
                        audio.append({**copy.deepcopy(track),'id':uid(),'source_sha256':source['sha256'],'start':track.get('start',0)+elapsed})
            subs=music_planning.captions(project['id'],db)
            if subs['source'].get('include_mp4'):captions.extend({**c,'start':c['start']+elapsed,'end':c['end']+elapsed} for c in subs['items'])
            elapsed+=span
    if len(clips)>500 or elapsed>4*3600:raise ValueError('Assemble up to 500 sequences or four hours at once. Export separate episodes for larger productions.')
    if music:
        master,_=music_planning.verified_master(production['episodes'][0]['sequences'][0]['project_id'])
        duration=master['body']['duration'];fps=settings['fps']
        if abs(elapsed-duration)>1/fps+.001:raise ValueError('The sequence lengths must add up to the locked song. Fit each sequence to its song section first.')
        audio.append({'id':uid(),'asset_id':master['asset_id'],'source_sha256':master['sha256'],'start':0,'trim_in':0,'trim_out':duration,'role':'music','volume':1,'duck':False})
    if not clips:raise ValueError('Choose at least one finished sequence.')
    snapshot={'project_id':production['root_project_id'],'scene_id':None,'title':production['title'],'timeline_revision':revision,'timeline':{'revision':revision,'settings':settings,'clips':clips,'audio':audio},'master_sequences':frozen,'captions':captions,'manual_override':True,'manual_requested_at':now()}
    return {'job_id':queue_snapshot('master_export',snapshot)['id']}


class Assembly(BaseModel):
    model_config=ConfigDict(extra='forbid')
    revision:int
    episode_ids:list[str]=Field(min_length=1,max_length=100)

@router.get('/{identifier}/master')
async def status(identifier:str,session=Depends(require_session)):return review(identifier)
@router.post('/{identifier}/master')
async def assemble(identifier:str,body:Assembly,session=Depends(require_session)):return await asyncio.to_thread(queue,identifier,**body.model_dump())
