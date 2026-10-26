import asyncio
import json
import logging

import httpx
from pydantic import BaseModel,ConfigDict,Field,ValidationError

from .config import settings
from .resources import resources
from .store import Conflict,db,encode,now,uid

log=logging.getLogger('studio.director')


class PlannedScene(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=160)
    summary:str=Field(min_length=1,max_length=2000)
    image_prompt:str=Field(min_length=10,max_length=6000)
    video_prompt:str=Field(min_length=10,max_length=6000)
    negative_prompt:str=Field(default='',max_length=2000)
    duration:float=Field(default=5,ge=1,le=5)
    start_state:str=Field(default='',max_length=1000)
    end_state:str=Field(default='',max_length=1000)
    transition:str=Field(default='cut',pattern='^(cut|fade|dissolve)$')


class StoryPlan(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(max_length=160)
    synopsis:str=Field(max_length=4000)
    style_guide:str=Field(max_length=5000)
    scenes:list[PlannedScene]=Field(min_length=1,max_length=40)


class OutlineScene(BaseModel):
    model_config=ConfigDict(extra='forbid')
    title:str=Field(min_length=1,max_length=160)
    summary:str=Field(min_length=1,max_length=1000)


class Outline(BaseModel):
    model_config=ConfigDict(extra='forbid')
    synopsis:str=Field(max_length=2000)
    style_guide:str=Field(max_length=3000)
    scenes:list[OutlineScene]=Field(min_length=1,max_length=40)


class DirectorAction(BaseModel):
    model_config=ConfigDict(extra='forbid')
    action:str=Field(pattern='^(create_scene|revise_scene|style_guide)$')
    scene_id:str|None=None
    title:str|None=Field(default=None,max_length=160)
    summary:str|None=Field(default=None,max_length=2000)
    image_prompt:str|None=Field(default=None,max_length=6000)
    video_prompt:str|None=Field(default=None,max_length=6000)
    value:str|None=Field(default=None,max_length=5000)


class DirectorReply(BaseModel):
    model_config=ConfigDict(extra='forbid')
    reply:str=Field(min_length=1,max_length=12000)
    actions:list[DirectorAction]=Field(default_factory=list,max_length=12)


def migrate():
    db.execute('CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY,project_id TEXT,job_id TEXT,kind TEXT,base_revision INTEGER,scene_revisions TEXT,body TEXT,status TEXT,created REAL)')


def context(project,selected=None):
    # A compact scene index preserves identity without sending every full prompt.
    index=[{'id':s['id'],'revision':s['revision'],'title':s['title'],'summary':s['body'].get('summary','')[:160]} for s in project['scenes'][:100]]
    detailed=[s for s in project['scenes'] if s['id']==selected][:1]
    return {'title':project['title'],'brief':project['brief'][:6000],'style_guide':project['settings'].get('style_guide','')[:2500],'characters':str(project['settings'].get('characters',[]))[:2000],'scene_index':index,'selected_scenes':[{'id':s['id'],'body':{k:str(v)[:1800] for k,v in s['body'].items() if k in ['summary','image_prompt','video_prompt']}} for s in detailed]}


async def model_details(model,client=None):
    async def fetch(c):
        tags=(await c.get(settings['ollama_url']+'/api/tags')).json().get('models',[])
        selected=next((item for item in tags if item['name']==model),None)
        if not selected:
            raise ValueError('The selected language model is not installed. Choose one shown in the local model selector.')
        if selected.get('remote_host') or selected.get('remote_model') or model.endswith('-cloud') or ':cloud' in model:
            raise ValueError('Choose a model installed on this computer. Cloud inference is disabled in Studio.')
        response=await c.post(settings['ollama_url']+'/api/show',json={'model':model})
        response.raise_for_status()
        return {**selected,'capabilities':response.json().get('capabilities',[])}
    if client:
        return await fetch(client)
    async with httpx.AsyncClient(timeout=20) as c:
        return await fetch(c)


async def llm_models():
    async with httpx.AsyncClient(timeout=20) as c:
        response=await c.get(settings['ollama_url']+'/api/tags');response.raise_for_status()
        return await asyncio.gather(*(model_details(m['name'],c) for m in response.json().get('models',[])))


async def prepare_gpu(client,model):
    details=await model_details(model,client)
    if 'completion' not in details['capabilities']:
        raise ValueError('This installed model does not support text generation.')
    loaded=await client.get(settings['ollama_url']+'/api/ps');loaded.raise_for_status()
    if loaded.json().get('models'):
        return 'Waiting for an existing Ollama session to unload. Studio will not evict it.'
    try:
        response=await client.get(settings['comfy_url']+'/queue',timeout=5)
        response.raise_for_status();queue=response.json()
        if queue.get('queue_running') or queue.get('queue_pending'):
            return 'Your Director request is waiting for a safe GPU window after the current ComfyUI work.'
        history=(await client.get(settings['comfy_url']+'/history',params={'max_items':1})).json()
        latest=next(iter(history.values()),{})
        prompt=latest.get('prompt',[])
        if len(prompt)>3 and prompt[3].get('sceneflow',{}).get('job_id'):
            # Release cached Studio weights only after rechecking that the backend is idle.
            fresh=(await client.get(settings['comfy_url']+'/queue')).json()
            if not fresh.get('queue_running') and not fresh.get('queue_pending'):
                await client.post(settings['comfy_url']+'/free',json={'unload_models':True,'free_memory':True})
    except httpx.HTTPError:
        pass
    telemetry=resources();gpu=telemetry.get('gpu')
    if gpu and gpu['free'] < details['size']+settings['vram_reserve_mb']*1024**2:
        return 'Not enough free GPU memory for this selected model. Release idle model memory or choose a smaller installed model.'
    if not gpu:
        return 'GPU memory could not be measured. Studio is waiting rather than loading another large model blindly.'
    return None


async def structured(client,model,messages,schema,options=None):
    conversation=list(messages)
    for attempt in range(2):
        response=await client.post(settings['ollama_url']+'/api/chat',json={'model':model,'messages':conversation,'format':schema.model_json_schema(),'stream':False,'think':False,'keep_alive':'5m','options':{'temperature':.55,'num_ctx':8192,'num_predict':6000,**(options or {})}},timeout=600)
        response.raise_for_status()
        value=response.json().get('message',{}).get('content','')
        try:
            return schema.model_validate_json(value)
        except (ValidationError,ValueError) as error:
            if attempt:
                raise ValueError('The local model returned invalid structured output twice. No project changes were applied.') from error
            conversation += [{'role':'assistant','content':value[:6000]},{'role':'user','content':'Return only valid JSON matching the supplied schema. Correct this validation error: '+str(error)[:1000]}]
    raise ValueError('The model did not return a valid plan.')


async def unload(client,model):
    response=await client.post(settings['ollama_url']+'/api/generate',json={'model':model,'keep_alive':0,'stream':False},timeout=60)
    response.raise_for_status()
    for _ in range(15):
        loaded=(await client.get(settings['ollama_url']+'/api/ps')).json().get('models',[])
        if not any(m.get('name')==model or m.get('model')==model for m in loaded):
            return True
        await asyncio.sleep(1)
    raise ValueError('Ollama did not confirm unloading the Studio model. Generation will wait for safe resources.')


def add_proposal(project,job_id,kind,body,snapshot=None):
    migrate()
    identifier=uid()
    revisions=(snapshot or {}).get('scene_revisions',{s['id']:s['revision'] for s in project['scenes']})
    base=(snapshot or {}).get('base_revision',project['revision'])
    db.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?,?,?)',(identifier,project['id'],job_id,kind,base,encode(revisions),encode(body),'pending',now()))
    db.event('director.proposal',{'project_id':project['id'],'proposal_id':identifier})
    return identifier


def apply_proposal(identifier):
    changed=[]
    with db.connect(True) as con:
        row=con.execute('SELECT * FROM proposals WHERE id=?',(identifier,)).fetchone()
        if not row or row['status']!='pending':
            raise Conflict('This proposal is missing or has already been applied.')
        proposal=dict(row);project=dict(con.execute('SELECT * FROM projects WHERE id=?',(row['project_id'],)).fetchone())
        if project['revision']!=proposal['base_revision']:
            raise Conflict('The project changed. Request a fresh proposal before applying it.')
        revisions=json.loads(proposal['scene_revisions']);body=json.loads(proposal['body']);config=json.loads(project['settings'])
        scenes={r['id']:dict(r) for r in con.execute('SELECT * FROM scenes WHERE project_id=?',(project['id'],))}
        creates=[];edits=[]
        if proposal['kind']=='plan':
            plan=StoryPlan.model_validate(body)
            if {k:v['revision'] for k,v in scenes.items()}!=revisions:
                raise Conflict('The storyboard changed while planning. Review a fresh plan.')
            creates=[(s.title,s.model_dump(exclude={'title'})) for s in plan.scenes]
            config.update(style_guide=plan.style_guide,synopsis=plan.synopsis)
        else:
            for action in DirectorReply.model_validate(body).actions:
                values=action.model_dump(exclude_none=True)
                creative={k:v for k,v in values.items() if k in ['summary','image_prompt','video_prompt']}
                if action.action=='create_scene':
                    creates.append((action.title or 'New scene',creative))
                elif action.action=='revise_scene':
                    scene=scenes.get(action.scene_id)
                    if not scene or scene['revision']!=revisions.get(action.scene_id) or any(e[0]['id']==scene['id'] for e in edits):
                        raise Conflict('A proposed scene changed or appears twice. No changes were applied.')
                    edits.append((scene,action.title or scene['title'],{**json.loads(scene['body']),**creative}))
                else:
                    config['style_guide']=action.value or ''
        position=max((s['position'] for s in scenes.values()),default=-1)+1
        for title,body in creates:
            sid,rid=uid(),uid();data={'summary':'','image_prompt':'','video_prompt':'','negative_prompt':'','duration':3,'seed':26102026,'locked':False,**body}
            con.execute('INSERT INTO scenes(id,project_id,title,position,revision,revision_id,body,created,updated) VALUES(?,?,?,?,?,?,?,?,?)',(sid,project['id'],title,position,1,rid,encode(data),now(),now()))
            con.execute('INSERT INTO scene_revisions VALUES(?,?,?,?,?)',(rid,sid,1,encode({'title':title,**data}),now()));position+=1
        for scene,title,data in edits:
            rid=uid();revision=scene['revision']+1
            con.execute('UPDATE scenes SET title=?,body=?,revision=?,revision_id=?,updated=? WHERE id=?',(title,encode(data),revision,rid,now(),scene['id']))
            con.execute('INSERT INTO scene_revisions VALUES(?,?,?,?,?)',(rid,scene['id'],revision,encode({'title':title,**data}),now()));changed.append(scene['id'])
        con.execute('UPDATE projects SET settings=?,revision=revision+1,updated=? WHERE id=?',(encode(config),now(),project['id']))
        con.execute("UPDATE proposals SET status='applied' WHERE id=?",(identifier,))
    from .production import supersede_pending
    for scene_id in changed:
        supersede_pending(scene_id)
    db.event('director.applied',{'project_id':project['id'],'proposal_id':identifier})
    return db.project(project['id'])


async def execute_ai(job,snapshot):
    from .production import produce,update_job
    model=snapshot['model'];project=db.project(job['project_id'])
    async with httpx.AsyncClient(timeout=30) as client:
        reason=await prepare_gpu(client,model)
        if reason:
            if job['error']!=reason:
                update_job(job['id'],'queued',error=reason)
            return
        update_job(job['id'],'running',started=now(),error=None)
        try:
            creative=snapshot['context']
            if job['kind']=='plan':
                system='You are a practical film director planning short image-first clips for local Qwen Image and Wan 2.2 on a 16 GB GPU. Produce separate still-image composition prompts and image-to-video motion prompts. Preserve character identity and style. Use one or two readable actions per shot, a locked camera unless requested, no unsupported transformations or camera cuts. Each duration must be between 1 and 5 seconds. Return the exact requested scene count. Do not invent installed capabilities. Character and style rules apply to every scene.'
                messages=[{'role':'system','content':system},{'role':'user','content':encode({'creative_context':creative,'scene_count':snapshot['scene_count']})}]
                if snapshot['scene_count']<=4:
                    plan=await structured(client,model,messages,StoryPlan)
                else:
                    outline=await structured(client,model,messages,Outline)
                    if len(outline.scenes)!=snapshot['scene_count']:
                        raise ValueError('The model returned the wrong outline count. Request planning again.')
                    detailed=[]
                    for start in range(0,len(outline.scenes),4):
                        batch=outline.scenes[start:start+4]
                        request={'creative_context':creative,'synopsis':outline.synopsis,'style_guide':outline.style_guide,'requested_scenes':[s.model_dump() for s in batch]}
                        part=await structured(client,model,[{'role':'system','content':system+' Detail only the supplied requested_scenes, in the same order.'},{'role':'user','content':encode(request)}],StoryPlan)
                        if len(part.scenes)!=len(batch):
                            raise ValueError('A planning batch returned the wrong count. No partial plan was applied.')
                        detailed.extend(part.scenes)
                        db.execute('UPDATE jobs SET progress=? WHERE id=?',(len(detailed)/snapshot['scene_count']*.9,job['id']))
                    plan=StoryPlan(title=project['title'],synopsis=outline.synopsis,style_guide=outline.style_guide,scenes=detailed)
                if len(plan.scenes)!=snapshot['scene_count']:
                    raise ValueError('The model returned the wrong number of scenes. No plan was committed.')
                proposal=add_proposal(project,job['id'],'plan',plan.model_dump(),snapshot)
                if snapshot.get('auto_apply') and not project['scenes'] and project['revision']==snapshot['base_revision']:
                    apply_proposal(proposal)
            else:
                system='You are a thoughtful local film director. Answer questions clearly. Propose typed actions only when the user asks for a creative change. Use exact scene IDs from context for scene edits, and never apply a request for one scene to all scenes. Actions are suggestions requiring user review. Never propose shell commands, code execution, filesystem access, network operations, model downloads, or unsupported generation features. Keep creative changes targeted and preserve character/style rules.'
                recent=snapshot.get('recent',[])
                messages=[{'role':'system','content':system+'\nProject context: '+encode(creative)}]+[{'role':r['role'],'content':r['content'][:1000]} for r in recent]
                if not messages or messages[-1].get('content')!=snapshot['message']:
                    messages.append({'role':'user','content':snapshot['message']})
                reply=await structured(client,model,messages,DirectorReply)
                db.execute('INSERT INTO chat VALUES(?,?,?,?,?)',(uid(),project['id'],'assistant',reply.reply,now()))
                if reply.actions:
                    add_proposal(project,job['id'],'director',reply.model_dump(),snapshot)
        finally:
            await unload(client,model)
        update_job(job['id'],'completed',progress=1,finished=now())
        if job['kind']=='plan' and snapshot.get('auto_continue'):
            produce(project['id'],'all')
