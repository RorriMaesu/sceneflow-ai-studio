import asyncio
import copy
import hashlib
import json
import logging
import time

import httpx
import websockets

from .adapters import graph_hash, registry
from .config import ROOT, settings
from .media import asset_path, collect_outputs, select_asset
from .resources import resources
from .store import db, encode, now, uid

log = logging.getLogger('studio.production')
ACTIVE = ('running','submitted','reconciling')


def migrate():
    with db.connect(True) as con:
        con.execute('CREATE TABLE IF NOT EXISTS production_state(project_id TEXT PRIMARY KEY,paused INTEGER DEFAULT 1,auto_run INTEGER DEFAULT 0)')
        con.execute('INSERT OR IGNORE INTO production_state(project_id) SELECT id FROM projects')
        con.execute('INSERT OR IGNORE INTO migrations VALUES(2,?)', (now(),))


def state(project_id):
    db.execute('INSERT OR IGNORE INTO production_state(project_id) VALUES(?)', (project_id,))
    return db.one('SELECT * FROM production_state WHERE project_id=?', (project_id,))


def pause(project_id, paused=True):
    state(project_id)
    db.execute('UPDATE production_state SET paused=? WHERE project_id=?', (int(paused), project_id))
    db.event('production.paused' if paused else 'production.resumed', {'project_id': project_id})
    return {'paused': paused}


def snapshot_for(scene, project, kind, source=None, config=None):
    body = scene['body']
    config = copy.deepcopy(config or project['settings'])
    workflow_id = body.get('image_workflow' if kind=='image' else 'video_workflow') or config['image_workflow' if kind=='image' else 'video_workflow']
    entry = registry.get(workflow_id)
    if entry['status'] != 'ready':
        raise ValueError('Choose a verified available workflow before generating: '+entry['name'])
    requested_duration = float(body.get('duration', 3))
    frames = int(config.get('frames',49))
    if kind == 'video':
        frames = int(round(requested_duration*int(config.get('fps',16))/4)*4+1)
        if frames > entry['constraints'].get('max_frames',81):
            raise ValueError('This scene is longer than the verified video preset. Choose five seconds or less, or import a compatible workflow.')
    data = {'project_id': project['id'], 'scene_id': scene['id'], 'scene_title': scene['title'], 'scene_revision_id': scene['revision_id'], 'scene_revision': scene['revision'], 'positive_prompt': body.get('image_prompt' if kind=='image' else 'video_prompt',''), 'negative_prompt': body.get('negative_prompt',''), 'image_prompt': body.get('image_prompt',''), 'video_prompt': body.get('video_prompt',''), 'workflow_id': workflow_id, 'workflow_hash': entry['workflow_hash'], 'workflow_definition': copy.deepcopy(entry), 'seed': int(body.get('seed',26102026)), 'width': int(config.get('width',640)), 'height': int(config.get('height',352)), 'frames': frames, 'fps': int(config.get('fps',16)), 'requested_duration': requested_duration, 'image_steps': int(config.get('image_steps',12)), 'config': config, 'source_asset_id': source['id'] if source else None, 'source_sha256': source['sha256'] if source else None}
    if not data['positive_prompt'].strip():
        raise ValueError('Write a '+('starting still' if kind=='image' else 'motion')+' prompt for '+scene['title']+' first.')
    if not 0 <= data['seed'] < 2**63 or not 1 <= data['image_steps'] <= 60 or not 1 <= data['fps'] <= 60:
        raise ValueError('Seed, steps, or frame rate is outside supported bounds.')
    if kind=='video' and (not source or source['kind']!='image' or source['scene_id']!=scene['id']):
        raise ValueError('Select a valid starting still from this scene before animating it.')
    return data


def queue_snapshot(kind, snapshot, automatic=False, force=False, dependencies=None, priority=0):
    frozen = copy.deepcopy(snapshot)
    frozen['automatic'] = automatic
    request_key = hashlib.sha256(encode({'kind':kind,'snapshot':frozen}).encode()).hexdigest()
    if not force:
        old = db.one("SELECT * FROM jobs WHERE request_key=? AND status NOT IN ('failed','cancelled','superseded')", (request_key,))
        if old:
            return old
    identifier = uid()
    attempt = db.one('SELECT COUNT(*) n FROM jobs WHERE scene_id=? AND kind=?', (snapshot.get('scene_id'),kind))['n']+1
    db.execute('INSERT INTO jobs(id,project_id,scene_id,kind,status,snapshot,dependencies,priority,request_key,attempt,created) VALUES(?,?,?,?,?,?,?,?,?,?,?)', (identifier, snapshot['project_id'], snapshot.get('scene_id'), kind, 'queued', encode(frozen), encode(dependencies or []), priority, request_key if not force else request_key+':'+identifier, attempt, now()))
    manifest = ROOT / 'projects' / snapshot['project_id'] / 'scenes' / (snapshot.get('scene_id') or 'production') / 'manifests' / (identifier+'.json')
    manifest.parent.mkdir(parents=True,exist_ok=True)
    manifest.write_text(json.dumps({'job_id':identifier,'attempt':attempt,'stage':kind,**frozen},indent=2),encoding='utf-8')
    db.event('job.queued',{'project_id':snapshot['project_id'],'scene_id':snapshot.get('scene_id'),'job_id':identifier})
    return db.one('SELECT * FROM jobs WHERE id=?',(identifier,))


def selected_source(scene):
    return db.one('SELECT * FROM assets WHERE id=? AND scene_id=? AND kind=?', (scene['selected_image_id'],scene['id'],'image')) if scene['selected_image_id'] else None


def current_source(scene):
    asset=selected_source(scene)
    if not asset or not asset['job_id']:
        return asset
    row=db.one('SELECT snapshot FROM jobs WHERE id=?',(asset['job_id'],))
    snap=json.loads(row['snapshot']) if row else {}
    return asset if snap.get('positive_prompt')==scene['body'].get('image_prompt','') and snap.get('negative_prompt','')==scene['body'].get('negative_prompt','') else None


def current_video(scene):
    asset = db.one('SELECT * FROM assets WHERE id=? AND source_asset_id=?', (scene['selected_video_id'],scene['selected_image_id'])) if scene['selected_video_id'] else None
    if not asset:
        return None
    job = db.one('SELECT snapshot FROM jobs WHERE id=?',(asset['job_id'],)) if asset['job_id'] else None
    return asset if job and json.loads(job['snapshot'])['positive_prompt']==scene['body'].get('video_prompt','') else None


def produce(project_id, scope='all', scene_id=None):
    project = db.project(project_id)
    scenes = [s for s in project['scenes'] if s['id']==scene_id] if scope.startswith('selected') else project['scenes']
    if not scenes:
        raise ValueError('Add or select a scene first.')
    automatic = scope=='all' and project['mode']!='manual'
    plans = []
    for scene in scenes:
        source = current_source(scene) if scope=='all' else selected_source(scene)
        if scope in ['stills','selected_still'] or (scope=='all' and not source):
            snap = snapshot_for(scene,project,'image')
            snap['continue_video'] = automatic
            count=int(project['settings'].get('candidates',1))
            if not 1<=count<=4:
                raise ValueError('Choose between one and four still candidates.')
            for candidate in range(count):
                variant=copy.deepcopy(snap);variant['seed']+=candidate;variant['candidate_index']=candidate
                plans.append(('image',variant))
        elif scope in ['videos','selected_video'] or (scope=='all' and not current_video(scene)):
            plans.append(('video',snapshot_for(scene,project,'video',source)))
    # Validate every requested scene before adding any jobs.
    state(project_id)
    with db.connect(True) as con:
        con.execute('UPDATE production_state SET paused=0,auto_run=? WHERE project_id=?',(int(automatic),project_id))
    jobs = [queue_snapshot(kind,snap,automatic=automatic,force=scope.startswith('selected'),priority=30 if scope.startswith('selected') else 0) for kind,snap in plans]
    if automatic and project['mode']=='hybrid' and any(project['settings'].get('gates',{}).get(k) for k in ['storyboard','prompts']):
        approved=project['settings'].get('planning_approved',{})
        for job in jobs:
            if approved.get(job['scene_id'])!=db.scene(job['scene_id'])['revision_id'] and job['status']=='queued':
                update_job(job['id'],'awaiting_review',error='Review the storyboard and prompts, then approve planning to release this work.')
    return {'jobs':[j['id'] for j in jobs],'planned':len(jobs),'reused_scenes':len(scenes)-len(jobs)}


def supersede_pending(scene_id):
    scene = db.scene(scene_id)
    project = db.project(scene['project_id'])
    pending = db.all("SELECT * FROM jobs WHERE scene_id=? AND status IN ('queued','awaiting_review')",(scene_id,))
    for job in pending:
        old = json.loads(job['snapshot'])
        source = selected_source(scene) if job['kind']=='video' else None
        if job['kind'] not in ['image','video'] or (job['kind']=='video' and not source):
            continue
        new = snapshot_for(scene,project,job['kind'],source,old['config'])
        new['continue_video'] = old.get('continue_video',False)
        new['candidate_index']=old.get('candidate_index',0)
        new['seed']+=new['candidate_index']
        # Preserve queued inputs unless a generation-relevant field changed.
        relevant = ['positive_prompt','negative_prompt','workflow_id','seed','source_asset_id','requested_duration']
        if any(old.get(k)!=new.get(k) for k in relevant):
            db.execute("UPDATE jobs SET status='superseded',finished=? WHERE id=? AND status IN ('queued','awaiting_review')",(now(),job['id']))
            replacement=queue_snapshot(job['kind'],new,automatic=old.get('automatic',False),priority=job['priority'])
            if job['status']=='awaiting_review':
                update_job(replacement['id'],'awaiting_review',error=job['error'])


def approve_and_continue(asset_id):
    result = select_asset(asset_id,True)
    asset = db.one('SELECT * FROM assets WHERE id=?',(asset_id,))
    project = db.project(asset['project_id'])
    scene = db.scene(asset['scene_id'])
    if asset['kind']=='image' and state(project['id'])['auto_run'] and project['mode']!='manual':
        queue_snapshot('video',snapshot_for(scene,project,'video',asset),automatic=True)
    return result


def update_job(identifier,status,**values):
    allowed = {'comfy_prompt_id','progress','error','started','finished'}
    if set(values)-allowed:
        raise ValueError('Invalid operational job update')
    columns = ['status=?']+[key+'=?' for key in values]
    db.execute('UPDATE jobs SET '+','.join(columns)+' WHERE id=?',(status,*values.values(),identifier))
    job = db.one('SELECT project_id,scene_id FROM jobs WHERE id=?',(identifier,))
    db.event('job.updated',{'job_id':identifier,'status':status,**(job or {})})


class Dispatcher:
    def __init__(self):
        self.task = None
        self.stopping = False
        self.last_family = None

    async def start(self):
        migrate()
        from .director import migrate as migrate_director
        migrate_director()
        db.execute("UPDATE jobs SET status='needs_attention',error='Agent restarted during a local AI request. Review any saved proposal before explicitly retrying.' WHERE status='running' AND kind IN ('plan','director','qa')")
        db.execute("UPDATE jobs SET status='queued',error='Restarting the frozen export after agent recovery.' WHERE status='running' AND kind='export'")
        db.execute("UPDATE jobs SET status='reconciling',error='Agent restarted; checking the original backend submission.' WHERE status IN ('running','submitted') AND kind IN ('image','video')")
        self.task = asyncio.create_task(self.loop())

    async def stop(self):
        self.stopping=True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def loop(self):
        while not self.stopping:
            try:
                active = db.one("SELECT * FROM jobs WHERE status IN ('submitted','reconciling','running') ORDER BY created LIMIT 1")
                if active:
                    await self.reconcile(active)
                else:
                    job = self.next_job()
                    if job:
                        await self.execute(job)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception('Dispatcher cycle failed')
            await asyncio.sleep(2)

    def next_job(self):
        jobs = db.all("SELECT * FROM jobs WHERE status='queued' ORDER BY priority DESC,CASE kind WHEN 'plan' THEN 0 WHEN 'director' THEN 0 WHEN 'image' THEN 1 WHEN 'qa' THEN 2 WHEN 'video' THEN 3 ELSE 4 END,created")
        for job in jobs:
            project = db.project(job['project_id'])
            control = state(job['project_id'])
            snap = json.loads(job['snapshot'])
            if control['paused'] or project['archived'] or (project['mode']=='manual' and snap.get('automatic')):
                continue
            dependencies = json.loads(job['dependencies'])
            if any(not db.one("SELECT id FROM jobs WHERE id=? AND status='completed'",(d,)) for d in dependencies):
                continue
            return job
        return None

    async def available(self,client,job):
        telemetry = resources()
        if telemetry['disk_free'] < settings['disk_reserve_gb']*1073741824:
            return 'Not enough project-drive space. Free space or adjust the storage reserve.'
        queue = await client.get(settings['comfy_url']+'/queue')
        queue.raise_for_status()
        value = queue.json()
        if value.get('queue_running') or value.get('queue_pending'):
            return 'Waiting for ComfyUI work started outside this studio. It will not be interrupted.'
        try:
            loaded = await client.get(settings['ollama_url']+'/api/ps')
            if loaded.status_code==200 and loaded.json().get('models'):
                return 'Waiting for loaded Ollama models to finish or unload. Other sessions are not interrupted.'
        except httpx.HTTPError:
            pass
        return None

    async def execute(self,job):
        snap = json.loads(job['snapshot'])
        try:
            if job['kind'] not in ['image','video']:
                await self.execute_other(job,snap)
                return
            async with httpx.AsyncClient(timeout=20) as client:
                reason = await self.available(client,job)
                if reason:
                    if reason != job['error']:
                        update_job(job['id'],'queued',error=reason)
                    return
                if not registry.info:
                    await registry.discover()
                prefix='sceneflow/'+job['project_id']+'/'+job['scene_id']+'/'+job['id']
                image = None
                if job['kind']=='video':
                    source = db.one('SELECT * FROM assets WHERE id=?',(snap['source_asset_id'],))
                    path = asset_path(snap['source_asset_id'])
                    with path.open('rb') as file:
                        digest = hashlib.file_digest(file,'sha256').hexdigest()
                    if not source or source['sha256']!=snap['source_sha256'] or digest!=snap['source_sha256']:
                        raise ValueError('The selected source still has changed on disk. Import or generate a verified replacement.')
                    with path.open('rb') as file:
                        response=await client.post(settings['comfy_url']+'/upload/image',files={'image':(job['id']+path.suffix,file)},data={'type':'input','overwrite':'false'})
                    response.raise_for_status()
                    uploaded=response.json()
                    image=(uploaded.get('subfolder','')+'/' if uploaded.get('subfolder') else '')+uploaded['name']
                graph,entry=registry.build(snap['workflow_id'],snap,prefix,image)
                submit_path=ROOT/'projects'/job['project_id']/'scenes'/job['scene_id']/'manifests'/(job['id']+'.submitted.json')
                submit_path.parent.mkdir(parents=True,exist_ok=True)
                submit_path.write_text(json.dumps({'job_id':job['id'],'source_asset_id':snap.get('source_asset_id'),'source_sha256':snap.get('source_sha256'),'workflow_hash':graph_hash(graph),'graph':graph},indent=2),encoding='utf-8')
                # The transaction claims the job before the only submission point.
                with db.connect(True) as con:
                    active=con.execute("SELECT id FROM jobs WHERE status IN ('running','submitted','reconciling') LIMIT 1").fetchone()
                    if active:
                        return
                    claimed=con.execute("UPDATE jobs SET status='running',started=?,error=NULL WHERE id=? AND status='queued'",(now(),job['id'])).rowcount
                if not claimed:
                    return
                try:
                    response=await client.post(settings['comfy_url']+'/prompt',json={'prompt':graph,'client_id':'sceneflow-'+job['id'],'extra_data':{'sceneflow':{'job_id':job['id'],'scene_id':job['scene_id'],'project_id':job['project_id']}}},timeout=30)
                except httpx.TransportError:
                    update_job(job['id'],'reconciling',error='The submission response was interrupted. Checking backend evidence before any retry.')
                    return
                if response.status_code != 200:
                    detail=response.json()
                    raise ValueError('ComfyUI rejected this workflow: '+str(detail.get('node_errors') or detail.get('error'))[:1500])
                identifier=response.json()['prompt_id']
                update_job(job['id'],'submitted',comfy_prompt_id=identifier,progress=.01,error=None)
                job=db.one('SELECT * FROM jobs WHERE id=?',(job['id'],))
                await self.wait_for_job(client,job,entry)
        except asyncio.CancelledError:
            raise
        except (httpx.HTTPError,ConnectionError) as error:
            if db.one("SELECT id FROM jobs WHERE id=? AND status='queued'",(job['id'],)):
                update_job(job['id'],'queued',error='ComfyUI is unavailable. Start the backend; this job has not been submitted.')
            else:
                update_job(job['id'],'reconciling',error='The backend disconnected. The original job will be reconciled; it will not be resubmitted automatically.')
        except Exception as error:
            log.exception('Job %s failed',job['id'])
            update_job(job['id'],'failed',error=str(error)[:1800],finished=now())

    async def progress_listener(self,job):
        url=settings['comfy_url'].replace('http:','ws:')+'/ws?clientId=sceneflow-'+job['id']
        try:
            async with websockets.connect(url,open_timeout=5,max_size=8*1024*1024) as ws:
                async for raw in ws:
                    if not isinstance(raw,str):
                        continue
                    message=json.loads(raw)
                    data=message.get('data',{})
                    if data.get('prompt_id') not in [None,job['comfy_prompt_id']]:
                        continue
                    if message.get('type')=='progress' and data.get('max',0):
                        # Sampler progress may reset at a second stage; label it as stage progress.
                        db.execute('UPDATE jobs SET progress=? WHERE id=? AND status IN (?,?)',(min(.94,max(.01,data['value']/data['max']*.9)),job['id'],'submitted','reconciling'))
                        db.event('job.progress',{'job_id':job['id'],'project_id':job['project_id'],'stage_progress':data['value']/data['max']})
        except (OSError,websockets.WebSocketException,ValueError):
            return

    async def wait_for_job(self,client,job,entry):
        listener=asyncio.create_task(self.progress_listener(job))
        try:
            while True:
                response=await client.get(settings['comfy_url']+'/history/'+job['comfy_prompt_id'])
                response.raise_for_status()
                history=response.json()
                if job['comfy_prompt_id'] in history:
                    result=history[job['comfy_prompt_id']]
                    status=result.get('status',{})
                    if status.get('status_str')=='error':
                        messages=status.get('messages',[])
                        errors=[x[1].get('exception_message','Generation failed') for x in messages if x[0]=='execution_error']
                        raise ValueError('ComfyUI generation failed: '+('; '.join(errors) or 'The backend interrupted this attempt.'))
                    if status.get('completed') or result.get('outputs'):
                        assets=await collect_outputs(client,job,result,entry)
                        await self.complete(job,assets)
                        return
                await asyncio.sleep(2)
        finally:
            listener.cancel()
            try:
                await listener
            except asyncio.CancelledError:
                pass

    async def reconcile(self,job):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                if not job['comfy_prompt_id']:
                    queue=(await client.get(settings['comfy_url']+'/queue')).json()
                    history=(await client.get(settings['comfy_url']+'/history',params={'max_items':300})).json()
                    candidates=list(queue.get('queue_running',[]))+list(queue.get('queue_pending',[]))+[r.get('prompt',[]) for r in history.values()]
                    found=next((item[1] for item in candidates if len(item)>3 and item[3].get('sceneflow',{}).get('job_id')==job['id']),None)
                    if not found:
                        update_job(job['id'],'needs_attention',error='No matching backend submission was found. The result is uncertain; review before explicitly retrying.',finished=now())
                        return
                    update_job(job['id'],'reconciling',comfy_prompt_id=found)
                    job['comfy_prompt_id']=found
                snap=json.loads(job['snapshot'])
                response=await client.get(settings['comfy_url']+'/history/'+job['comfy_prompt_id'])
                response.raise_for_status()
                if job['comfy_prompt_id'] not in response.json():
                    queue=(await client.get(settings['comfy_url']+'/queue')).json()
                    identifiers=[item[1] for item in queue.get('queue_running',[])+queue.get('queue_pending',[])]
                    if job['comfy_prompt_id'] not in identifiers:
                        update_job(job['id'],'needs_attention',error='The original backend job is missing from queue and history. Review before creating another attempt.',finished=now())
                        return
                await self.wait_for_job(client,job,snap['workflow_definition'])
        except httpx.HTTPError:
            return
        except Exception as error:
            update_job(job['id'],'failed',error=str(error)[:1800],finished=now())

    async def complete(self,job,assets):
        snap=json.loads(job['snapshot'])
        project=db.project(job['project_id'])
        candidate=next(a for a in assets if a['kind']==job['kind'])
        auto_approve=(project['mode']=='automatic' and project['settings'].get('auto_approve_'+job['kind']+'s',True)) or (project['mode']=='hybrid' and not project['settings'].get('gates',{}).get(job['kind'],True))
        # Never let an old render silently replace a newly revised/selected scene.
        scene=db.scene(job['scene_id'])
        current=scene['revision_id']==snap['scene_revision_id']
        already_selected=current_source(scene) if job['kind']=='image' else current_video(scene)
        if current and auto_approve and not already_selected:
            select_asset(candidate['id'])
            db.execute('UPDATE assets SET approved=1,approval_source=? WHERE id=?',('automatic_first_technically_valid',candidate['id']))
        update_job(job['id'],'completed',progress=1,finished=now(),error=None)
        registry.verified(snap['workflow_id'],{'job_id':job['id'],'asset_id':candidate['id'],'metadata':json.loads(candidate['metadata'])})
        if current and auto_approve and not already_selected and job['kind']=='image' and snap.get('continue_video') and state(project['id'])['auto_run']:
            new_snap=snapshot_for(db.scene(scene['id']),project,'video',candidate,snap['config'])
            queue_snapshot('video',new_snap,automatic=True,dependencies=[job['id']])
        if job['kind']=='video' and auto_approve:
            await self.maybe_export(project['id'])

    async def maybe_export(self,project_id):
        project=db.project(project_id)
        gates=project['settings'].get('gates',{})
        can_export=project['mode']=='automatic' or (project['mode']=='hybrid' and not gates.get('timeline',True))
        if can_export and project['settings'].get('auto_export',True) and state(project_id)['auto_run'] and all(current_video(s) for s in project['scenes']):
            from .exports import rebuild_timeline, queue_export
            rebuild_timeline(project_id)
            queue_export(project_id,automatic=True)

    async def execute_other(self,job,snapshot):
        if job['kind'] in ['plan','director']:
            from .director import execute_ai
            await execute_ai(job,snapshot)
        elif job['kind']=='export':
            from .exports import execute_export
            update_job(job['id'],'running',started=now())
            await asyncio.to_thread(execute_export,job,snapshot)
            update_job(job['id'],'completed',progress=1,finished=now())
        else:
            raise ValueError('This job type is not enabled in the current build.')


dispatcher=Dispatcher()
