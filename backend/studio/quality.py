"""Optional local vision review. Scores are advisory, not calibrated probabilities."""
import asyncio
import base64
import copy
import hashlib
import io
import json

import httpx
from PIL import Image,ImageChops,ImageStat
from pydantic import BaseModel,ConfigDict,Field

from .config import ROOT
from .director import model_details,prepare_gpu,structured,unload
from .media import asset_path,executable,run_tool,verify
from .store import db,encode,now,uid


class Issue(BaseModel):
    model_config=ConfigDict(extra='forbid')
    description:str=Field(max_length=1000)
    severity:str=Field(pattern='^(low|medium|high)$')


class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    overall_score:float=Field(ge=0,le=1)
    prompt_adherence:float=Field(ge=0,le=1)
    visual_quality:float=Field(ge=0,le=1)
    character_consistency:float=Field(ge=0,le=1)
    motion_consistency:float|None=Field(default=None,ge=0,le=1)
    issues:list[Issue]=Field(max_length=12)
    recommendation:str=Field(pattern='^(accept|review|regenerate)$')
    confidence:str=Field(pattern='^(low|moderate|high)$')
    explanation:str=Field(max_length=2000)


def samples(asset):
    path=asset_path(asset['id']);metadata=verify(path,asset['kind']);frames=[]
    if asset['kind']=='image':
        with Image.open(path) as image:frames.append(image.convert('RGB').copy())
    else:
        duration=metadata['duration']
        root=ROOT/'temp'/('qa-'+asset['id']);root.mkdir(parents=True,exist_ok=True)
        for index,at in enumerate([0,duration*.5,max(0,duration-1/max(1,metadata['fps']))]):
            target=root/f'{index}.png'
            run_tool([executable('ffmpeg'),'-y','-v','error','-ss',str(at),'-i',str(path),'-frames:v','1','-vf','scale=512:512:force_original_aspect_ratio=decrease',str(target)])
            with Image.open(target) as image:frames.append(image.convert('RGB').copy())
    means=[];encoded=[];differences=[]
    for frame in frames:
        frame.thumbnail((512,512));means.append(sum(ImageStat.Stat(frame).mean)/3)
        buffer=io.BytesIO();frame.save(buffer,format='JPEG',quality=85);encoded.append(base64.b64encode(buffer.getvalue()).decode())
    for a,b in zip(frames,frames[1:]):
        differences.append(sum(ImageStat.Stat(ImageChops.difference(a,b.resize(a.size))).mean)/3)
    technical={'decoded':True,'metadata':metadata,'sample_count':len(frames),'mean_sample_luminance':means,'sample_differences':differences,'dark_samples':sum(m<2 for m in means),'nearly_identical_samples':bool(differences and max(differences)<.3),'limits':'Three video samples cannot establish complete motion adherence, detect all flicker, or evaluate sound.'}
    return encoded,technical


async def queue_review(asset_id,model=None,automatic=False):
    from .production import pause,queue_snapshot
    asset=db.one('SELECT * FROM assets WHERE id=?',(asset_id,))
    if not asset or asset['kind'] not in ['image','video']:raise ValueError('Choose a scene still or video for visual review.')
    project=db.project(asset['project_id']);model=model or project['settings'].get('qa_model')
    if not model or model=='auto':
        from .director import llm_models
        models=[m for m in await llm_models() if 'vision' in m['capabilities'] and not m.get('remote_host')]
        if not models:raise ValueError('No installed local vision model was found. Continue with manual review or disable AI QA.')
        model=min(models,key=lambda m:m['size'])['name']
    details=await model_details(model)
    if 'vision' not in details['capabilities']:raise ValueError('The selected QA model does not advertise vision support.')
    scene=db.scene(asset['scene_id']);generation=db.one('SELECT snapshot FROM jobs WHERE id=?',(asset['job_id'],)) if asset['job_id'] else None
    frozen=json.loads(generation['snapshot']) if generation else {}
    snapshot={'project_id':project['id'],'scene_id':scene['id'],'scene_title':scene['title'],'asset_id':asset_id,'asset_sha256':asset['sha256'],'model':model,'generation_job_id':asset['job_id'],'allow_actions':automatic,'scene_revision_id':json.loads(asset['metadata']).get('scene_revision_id',scene['revision_id']),'scene_brief':frozen.get('scene_brief',scene['body'].get('summary','')),'image_prompt':frozen.get('image_prompt',scene['body'].get('image_prompt','')),'video_prompt':frozen.get('video_prompt',scene['body'].get('video_prompt','')),'qa_policy':{k:copy.deepcopy(project['settings'].get(k)) for k in ['qa_rubric','qa_threshold','qa_regenerate','max_retries']}}
    pause(project['id'],False)
    return queue_snapshot('qa',snapshot,automatic=automatic,force=not automatic,priority=0 if automatic else -20)


def threshold(policy):
    value=policy.get('qa_threshold')
    return float(value) if value is not None else {'lenient':.5,'balanced':.7,'strict':.85}.get(policy.get('qa_rubric'),.7)


def retry_allowed(store,job,snapshot,score):
    policy=snapshot['qa_policy']
    if not policy.get('qa_regenerate'):return False
    original=json.loads(job['snapshot']);kind=job['kind'];limit=min(2,max(0,int(policy.get('max_retries') or 2)))
    attempts=[j for j in store.jobs(job['project_id']) if j['scene_id']==job['scene_id'] and j['kind']==kind and j['snapshot'].get('quality_retry') and j['snapshot'].get('scene_revision_id')==original.get('scene_revision_id')]
    if len(attempts)>=limit:return False
    prior=store.all('SELECT q.body FROM qa q JOIN assets a ON a.id=q.asset_id WHERE a.scene_id=? AND a.kind=?',(job['scene_id'],kind))
    previous=[json.loads(r['body'])['overall_score'] for r in prior if json.loads(r['body']).get('asset_id')!=snapshot['asset_id'] and json.loads(r['body']).get('scene_revision_id')==snapshot['scene_revision_id']]
    if attempts and previous and score<=max(previous):return False
    return True


async def apply_result(asset,qa_job,snapshot,result):
    from .production import Dispatcher,queue_snapshot,supersede_pending,snapshot_is_current
    if not snapshot.get('allow_actions'):return
    project=db.project(asset['project_id']);scene=db.scene(asset['scene_id'])
    # An explicit approval always wins, including one made while QA was running.
    fresh=db.one('SELECT * FROM assets WHERE id=?',(asset['id'],))
    if fresh['approval_source']=='user':return
    generation=db.one('SELECT * FROM jobs WHERE id=?',(asset['job_id'],)) if asset['job_id'] else None
    if generation and not project['settings'].get('qa_enabled'):
        await Dispatcher().finalize(generation,asset);return
    if not generation or not snapshot_is_current(json.loads(generation['snapshot']),scene,project,generation['kind']):return
    selected=scene['selected_image_id' if asset['kind']=='image' else 'selected_video_id']
    chosen=db.one('SELECT * FROM assets WHERE id=?',(selected,)) if selected else None
    if chosen and chosen['approval_source']=='user':return
    accepted=result['recommendation']=='accept' and result['overall_score']>=threshold(snapshot['qa_policy'])
    if accepted:
        if chosen:
            previous=db.one('SELECT body FROM qa WHERE asset_id=? ORDER BY created DESC LIMIT 1',(chosen['id'],))
            if previous and json.loads(previous['body'])['overall_score']>=result['overall_score']:return
        await Dispatcher().finalize(generation,asset,quality_accepted=True)
        supersede_pending(scene['id'])
    elif result['recommendation']=='regenerate' and result['overall_score']<threshold(snapshot['qa_policy']) and any(i['severity'] in ['medium','high'] for i in result['issues']) and not chosen and retry_allowed(db,generation,snapshot,result['overall_score']):
        frozen=json.loads(generation['snapshot']);frozen['quality_retry']=int(frozen.get('quality_retry',0))+1;frozen['seed']=(frozen['seed']+1009)%(2**63)
        queue_snapshot(generation['kind'],frozen,automatic=True,force=True)


async def execute(job,snapshot):
    from .production import update_job
    asset=db.one('SELECT * FROM assets WHERE id=?',(snapshot['asset_id'],))
    if not asset:raise ValueError('The asset for QA no longer exists.')
    project=db.project(asset['project_id'])
    if snapshot.get('automatic') and not project['settings'].get('qa_enabled'):
        update_job(job['id'],'cancelled',error='Automatic visual QA was disabled before this request started.',finished=now())
        generation=db.one('SELECT * FROM jobs WHERE id=?',(asset['job_id'],))
        if generation:
            from .production import Dispatcher
            await Dispatcher().finalize(generation,asset)
        return
    path=asset_path(asset['id'])
    with path.open('rb') as file:
        if hashlib.file_digest(file,'sha256').hexdigest()!=snapshot['asset_sha256']:raise ValueError('The asset changed before visual QA.')
    async with httpx.AsyncClient(timeout=30) as client:
        details=await model_details(snapshot['model'],client)
        if 'vision' not in details['capabilities']:raise ValueError('The selected model is not vision-capable. Manual approval is still available.')
        reason=await prepare_gpu(client,snapshot['model'])
        if reason:
            update_job(job['id'],'queued',error=reason);return
        update_job(job['id'],'running',started=now(),error=None)
        try:
            images,technical=await asyncio.to_thread(samples,asset)
            prompt='Evaluate these actual images against the exact requested subjects, props, composition, lighting and style. Score 0 means total failure, 0.5 means a partial match, and 1 means a fully successful match with no material defects. Higher is better. Scores are advisory rubric values, not calibrated probabilities. Be critical of prompt mismatch. For video, the images are first, middle and last samples; they do not prove complete motion or audio. Do not claim to hear audio. Return the requested schema. Accept a strong match without major issues; recommend regenerate only for a low-scoring clear actionable failure. Use review for ambiguous cases. Your recommendation and scores must agree.'
            creative={k:snapshot[k] for k in ['scene_brief','image_prompt','video_prompt']}
            reviewed=await structured(client,snapshot['model'],[{'role':'system','content':prompt},{'role':'user','content':encode({'requirements':creative,'kind':asset['kind'],'rubric':snapshot['qa_policy'].get('qa_rubric') or 'balanced'}),'images':images}],Review,{'temperature':.15,'num_predict':2000})
            result={**reviewed.model_dump(),'asset_id':asset['id'],'scene_revision_id':snapshot['scene_revision_id'],'qa_model':snapshot['model'],'technical_integrity':True,'technical':technical,'advisory':True}
            if result['recommendation']=='regenerate' and (result['overall_score']>=threshold(snapshot['qa_policy']) or not any(i['severity'] in ['medium','high'] for i in result['issues'])):
                result['raw_recommendation']=result['recommendation'];result['recommendation']='review';result['consistency_note']='The model recommendation conflicts with its score or actionable issues. Human review is required.'
            db.execute('INSERT INTO qa VALUES(?,?,?,?,?)',(uid(),asset['id'],snapshot['model'],encode(result),now()))
        finally:
            await unload(client,snapshot['model'])
        update_job(job['id'],'completed',progress=1,finished=now(),error=None)
        await apply_result(asset,job,snapshot,result)
        db.event('qa.completed',{'project_id':asset['project_id'],'asset_id':asset['id']})
