import asyncio
import copy
import importlib
import json

import pytest
import httpx
from PIL import Image

from studio.store import Store,encode,now,uid


@pytest.fixture
def engine(tmp_path,monkeypatch,request):
    store=Store(tmp_path/'studio.sqlite')
    modules={name:importlib.import_module('studio.'+name) for name in ['production','adapters','media','exports','storage']}
    for module in modules.values():
        monkeypatch.setattr(module,'db',store)
    modules['production'].migrate()
    from studio.adapters import BUILTINS,DUMMY,qwen_graph,wan_graph,graph_hash
    for original in BUILTINS:
        entry={**original,'status':'ready','reasons':[],'tested':False,'graph':qwen_graph(DUMMY,'test') if original['task']=='text_to_image' else wan_graph(DUMMY,'test','example.png')}
        entry['workflow_hash']=graph_hash(entry['graph'])
        store.execute('INSERT INTO workflow_registry VALUES(?,?,?)',(entry['id'],encode(entry),now()))
    project=store.create_project('Isolation test',mode='hybrid')
    count=20 if any(t in request.node.name for t in ['twenty_scene','duplicate_batch','manual_policy']) else 5 if 'live_edit' in request.node.name else 2
    scenes=[store.add_scene(project['id'],'Scene '+str(i),{'image_prompt':'still '+str(i),'video_prompt':'motion '+str(i),'duration':3}) for i in range(count)]
    return store,modules,project,scenes


def test_twenty_scene_jobs_have_distinct_frozen_prompts(engine):
    store,m,p,scenes=engine
    m['production'].produce(p['id'],'stills')
    jobs=store.jobs(p['id'])
    assert len(jobs)==20
    assert len({j['scene_id'] for j in jobs})==20
    for job in jobs:
        expected=next(s for s in scenes if s['id']==job['scene_id'])
        assert job['snapshot']['positive_prompt']==expected['body']['image_prompt']
        assert job['snapshot']['scene_revision_id']==expected['revision_id']


def test_guided_stage_requests_are_atomic_scoped_and_keep_pause(engine):
    store,m,p,scenes=engine
    m['production'].pause(p['id'],True)
    with pytest.raises(ValueError,match='owned by this project'):
        m['production'].produce(p['id'],'missing_stills',scene_ids=[scenes[0]['id'],'foreign'])
    assert not store.jobs(p['id'])
    result=m['production'].produce(p['id'],'missing_stills',scene_ids=[scenes[0]['id']])
    assert result['planned']==1 and m['production'].state(p['id'])['paused']==1
    job=store.jobs(p['id'])[0]
    assert job['scene_id']==scenes[0]['id'] and job['snapshot']['manual_override'] and not job['snapshot']['automatic']
    assert m['production'].produce(p['id'],'missing_videos',scene_ids=[scenes[1]['id']])['planned']==0


def test_elapsed_budget_pauses_before_new_jobs_and_resume_starts_new_window(engine):
    store,m,p,scenes=engine
    store.update_project(p['id'],1,{'mode':'automatic','settings':{'run_budget_minutes':1}})
    m['production'].produce(p['id'],'all');store.execute('UPDATE production_runs SET started=? WHERE project_id=?',(now()-61,p['id']))
    dispatcher=m['production'].Dispatcher()
    assert dispatcher.next_job() is None and m['production'].state(p['id'])['paused']==1
    assert all(j['status']=='queued' for j in store.jobs(p['id']))
    m['production'].pause(p['id'],False)
    assert dispatcher.next_job() and m['production'].state(p['id'])['paused']==0


def test_multiple_video_attempts_keep_same_exact_source(engine):
    store,m,p,scenes=engine
    store.update_project(p['id'],1,{'settings':{'video_attempts':3}})
    identifier=uid();store.execute('INSERT INTO assets(id,project_id,scene_id,kind,sha256,metadata) VALUES(?,?,?,?,?,?)',(identifier,p['id'],scenes[0]['id'],'image','source-hash','{}'))
    store.execute('UPDATE scenes SET selected_image_id=? WHERE id=?',(identifier,scenes[0]['id']))
    m['production'].produce(p['id'],'selected_video',scenes[0]['id'])
    jobs=store.jobs(p['id']);assert len(jobs)==3
    assert len({j['snapshot']['seed'] for j in jobs})==3
    assert all(j['snapshot']['source_asset_id']==identifier and j['snapshot']['source_sha256']=='source-hash' for j in jobs)


def test_failed_automatic_job_stop_policy_preserves_other_work(engine):
    store,m,p,scenes=engine
    store.update_project(p['id'],1,{'mode':'automatic','settings':{'failure_policy':'stop'}})
    m['production'].produce(p['id'],'all');job=store.one('SELECT * FROM jobs ORDER BY created LIMIT 1')
    m['production'].update_job(job['id'],'failed',finished=now(),error='Controlled failure')
    asyncio.run(m['production'].Dispatcher().failure_policy(job))
    assert m['production'].state(p['id'])['paused']==1
    assert store.one("SELECT COUNT(*) n FROM jobs WHERE status='queued'")['n']==len(scenes)-1


def test_failed_export_is_never_automatically_retried_by_partial_policy(engine,monkeypatch):
    store,m,p,scenes=engine
    store.update_project(p['id'],1,{'mode':'automatic','settings':{'failure_policy':'partial'}})
    job=m['production'].queue_snapshot('export',{'project_id':p['id'],'title':'Controlled export'},automatic=True)
    m['production'].update_job(job['id'],'failed',error='Controlled failure')
    async def forbidden(*args):raise AssertionError('Failed exports must not loop through partial generation policy')
    dispatcher=m['production'].Dispatcher();monkeypatch.setattr(dispatcher,'maybe_partial',forbidden)
    asyncio.run(dispatcher.failure_policy(job))
    assert len(store.jobs(p['id']))==1


def test_explicit_scene_work_does_not_resume_paused_automatic_production(engine):
    store,m,p,scenes=engine
    store.update_project(p['id'],1,{'mode':'automatic'})
    m['production'].produce(p['id'],'all');m['production'].pause(p['id'],True)
    m['production'].produce(p['id'],'selected_still',scenes[1]['id'])
    assert m['production'].state(p['id'])['paused']==1
    job=m['production'].Dispatcher().next_job()
    assert job and job['scene_id']==scenes[1]['id'] and not json.loads(job['snapshot'])['automatic']


def test_performance_estimates_use_only_matching_observed_presets(engine):
    from studio.insights import performance
    store,m,p,scenes=engine
    snapshot=m['production'].snapshot_for(scenes[0],p,'image')
    for index,seconds in enumerate([10,20,30]):
        job=m['production'].queue_snapshot('image',snapshot,force=True)
        store.execute("UPDATE jobs SET status='completed',started=?,finished=? WHERE id=?",(100+index*100,100+index*100+seconds,job['id']))
    m['production'].queue_snapshot('image',snapshot,force=True)
    result=performance(store,p['id'])
    assert result['presets'][0]['median_seconds']==20 and result['presets'][0]['samples']==3
    assert result['queued_observed_range_seconds']==[10,30] and result['unknown_jobs']==0
    unknown={**snapshot,'width':832};m['production'].queue_snapshot('image',unknown,force=True)
    assert performance(store,p['id'])['unknown_jobs']==1


def test_live_edit_only_supersedes_affected_pending_work(engine):
    store,m,p,scenes=engine
    m['production'].produce(p['id'],'stills')
    active=store.one('SELECT * FROM jobs WHERE scene_id=?',(scenes[1]['id'],))
    m['production'].update_job(active['id'],'submitted',comfy_prompt_id='original-comfy-id')
    old_snapshot=store.one('SELECT snapshot FROM jobs WHERE id=?',(active['id'],))['snapshot']
    store.update_scene(scenes[4]['id'],1,body={'image_prompt':'revised future scene'})
    m['production'].supersede_pending(scenes[4]['id'])
    assert store.one('SELECT snapshot FROM jobs WHERE id=?',(active['id'],))['snapshot']==old_snapshot
    changed=store.all("SELECT * FROM jobs WHERE scene_id=? AND status='queued'",(scenes[4]['id'],))
    assert len(changed)==1 and json.loads(changed[0]['snapshot'])['positive_prompt']=='revised future scene'
    assert store.one("SELECT COUNT(*) n FROM jobs WHERE status='superseded'")['n']==1


def test_edit_active_scene_preserves_manifest(engine):
    store,m,p,scenes=engine
    m['production'].produce(p['id'],'selected_still',scenes[0]['id'])
    job=store.one('SELECT * FROM jobs WHERE scene_id=?',(scenes[0]['id'],))
    m['production'].update_job(job['id'],'submitted',comfy_prompt_id='active')
    store.update_scene(scenes[0]['id'],1,body={'image_prompt':'new revision'})
    m['production'].supersede_pending(scenes[0]['id'])
    assert store.one('SELECT snapshot FROM jobs WHERE id=?',(job['id'],))['snapshot']==job['snapshot']


def test_duplicate_batch_submission_is_idempotent(engine):
    store,m,p,scenes=engine
    m['production'].produce(p['id'],'stills');m['production'].produce(p['id'],'stills')
    assert len(store.jobs(p['id']))==20


def test_video_cannot_be_queued_without_its_exact_scene_still(engine):
    store,m,p,scenes=engine
    with pytest.raises(ValueError,match='starting still'):
        m['production'].produce(p['id'],'selected_video',scenes[0]['id'])
    foreign={'id':uid(),'kind':'image','scene_id':scenes[1]['id'],'sha256':'hash'}
    with pytest.raises(ValueError,match='starting still'):
        m['production'].snapshot_for(scenes[0],p,'video',foreign)


def test_review_does_not_block_independent_queued_scenes(engine):
    store,m,p,scenes=engine
    m['production'].produce(p['id'],'stills')
    first=store.one('SELECT * FROM jobs WHERE scene_id=?',(scenes[0]['id'],))
    m['production'].update_job(first['id'],'completed')
    next_job=m['production'].Dispatcher().next_job()
    assert next_job and next_job['scene_id']!=scenes[0]['id']


def test_manual_policy_holds_automatic_jobs_without_deleting(engine):
    store,m,p,scenes=engine
    m['production'].produce(p['id'],'all')
    updated=store.update_project(p['id'],p['revision'],{'mode':'manual'})
    assert m['production'].Dispatcher().next_job() is None
    assert len(store.jobs(p['id']))==20
    store.update_project(p['id'],updated['revision'],{'mode':'automatic'})
    assert m['production'].Dispatcher().next_job() is not None


def test_workflow_mapping_is_frozen_in_job_snapshot(engine):
    store,m,p,scenes=engine
    snap=m['production'].snapshot_for(scenes[0],p,'image')
    original=copy.deepcopy(snap['workflow_definition'])
    entry=m['adapters'].registry.get('qwen-image-21');entry['status']='unavailable'
    store.execute('UPDATE workflow_registry SET body=? WHERE id=?',(encode(entry),entry['id']))
    graph,frozen=m['adapters'].registry.build('qwen-image-21',snap,'prefix')
    assert frozen==original


def test_output_collection_rejects_windows_path_escapes(engine):
    _,m,_,_=engine
    for filename in ['../secret','C:\\secret.png','file.png:stream','\\\\server\\share\\file.png']:
        with pytest.raises(ValueError):
            m['media'].validate_comfy_reference({'filename':filename,'subfolder':'','type':'output'})
    with pytest.raises(ValueError):
        m['media'].validate_comfy_reference({'filename':'safe.png','subfolder':'../outside','type':'output'})


def test_missing_backend_does_not_trigger_second_submission(engine,monkeypatch):
    store,m,p,scenes=engine
    m['production'].produce(p['id'],'selected_still',scenes[0]['id'])
    job=store.one('SELECT * FROM jobs WHERE scene_id=?',(scenes[0]['id'],))
    m['production'].update_job(job['id'],'reconciling')
    job=store.one('SELECT * FROM jobs WHERE id=?',(job['id'],))
    requests=[]
    def handler(request):
        requests.append(request.method)
        return httpx.Response(200,json={} if '/history' in str(request.url) else {'queue_running':[],'queue_pending':[]})
    factory=httpx.AsyncClient
    monkeypatch.setattr(m['production'].httpx,'AsyncClient',lambda **kwargs:factory(transport=httpx.MockTransport(handler),**kwargs))
    asyncio.run(m['production'].Dispatcher().reconcile(job))
    assert store.one('SELECT status FROM jobs WHERE id=?',(job['id'],))['status']=='needs_attention'
    assert store.one('SELECT COUNT(*) n FROM jobs')['n']==1
    assert all(method=='GET' for method in requests)


def test_accepted_before_response_is_reattached_without_resubmission(engine,monkeypatch):
    store,m,p,scenes=engine
    m['production'].produce(p['id'],'selected_still',scenes[0]['id'])
    job=store.one('SELECT * FROM jobs WHERE scene_id=?',(scenes[0]['id'],))
    m['production'].update_job(job['id'],'reconciling');job['status']='reconciling'
    calls=[]
    prompt=[0,'accepted-prompt',{}, {'sceneflow':{'job_id':job['id']}},[]]
    def handler(request):
        calls.append(request.method)
        if request.url.path=='/queue':return httpx.Response(200,json={'queue_running':[prompt],'queue_pending':[]})
        return httpx.Response(200,json={})
    factory=httpx.AsyncClient
    monkeypatch.setattr(m['production'].httpx,'AsyncClient',lambda **kw:factory(transport=httpx.MockTransport(handler),**kw))
    seen=[]
    async def wait(client,recovered,entry):seen.append(recovered['comfy_prompt_id'])
    dispatcher=m['production'].Dispatcher();monkeypatch.setattr(dispatcher,'wait_for_job',wait)
    asyncio.run(dispatcher.reconcile(job))
    assert seen==['accepted-prompt']
    assert store.one('SELECT comfy_prompt_id FROM jobs WHERE id=?',(job['id'],))['comfy_prompt_id']=='accepted-prompt'
    assert all(method=='GET' for method in calls)


def test_twenty_scene_automatic_pipeline_preserves_every_source(engine):
    store,m,p,scenes=engine
    store.update_project(p['id'],1,{'mode':'automatic','settings':{'auto_export':False}})
    m['production'].produce(p['id'],'all');dispatcher=m['production'].Dispatcher()
    def finish(job):
        snapshot=json.loads(job['snapshot']);asset_id=uid()
        relative='projects/'+p['id']+'/test/'+asset_id+'.png'
        path=m['media'].ROOT/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'test media placeholder')
        store.execute('INSERT INTO assets(id,project_id,scene_id,job_id,source_asset_id,kind,path,sha256,metadata,created) VALUES(?,?,?,?,?,?,?,?,?,?)',(asset_id,p['id'],job['scene_id'],job['id'],snapshot.get('source_asset_id'),job['kind'],relative,asset_id,encode({'duration':3}),now()))
        asset=store.one('SELECT * FROM assets WHERE id=?',(asset_id,))
        asyncio.run(dispatcher.complete(job,[asset]))
    for job in store.all("SELECT * FROM jobs WHERE project_id=? AND kind='image'",(p['id'],)):finish(job)
    videos=store.all("SELECT * FROM jobs WHERE project_id=? AND kind='video'",(p['id'],))
    assert len(videos)==20
    for job in videos:
        snapshot=json.loads(job['snapshot']);scene=store.scene(job['scene_id'])
        assert snapshot['source_asset_id']==scene['selected_image_id']
        assert snapshot['positive_prompt']==scene['body']['video_prompt']
        finish(job)
    assert store.one("SELECT COUNT(*) n FROM jobs WHERE status='completed'")['n']==40
    assert all(s['selected_image_id'] and s['selected_video_id'] for s in store.project(p['id'])['scenes'])


def test_stage_invalidation_preserves_still_for_motion_edits(engine):
    store,m,p,scenes=engine;scene=scenes[0]
    still=m['production'].snapshot_for(scene,p,'image')
    changed=store.update_scene(scene['id'],1,body={'video_prompt':'New motion only','duration':4})
    assert m['production'].snapshot_is_current(still,changed,p,'image')
    source={'id':uid(),'scene_id':scene['id'],'kind':'image','sha256':'hash'}
    video=m['production'].snapshot_for(changed,p,'video',source)
    changed['selected_image_id']=source['id']
    assert m['production'].snapshot_is_current(video,changed,p,'video')
    changed['body']['duration']=2
    assert not m['production'].snapshot_is_current(video,changed,p,'video')
    changed['body']['image_prompt']='A new composition'
    assert not m['production'].snapshot_is_current(still,changed,p,'image')


def test_foreign_comfy_work_is_observed_without_interrupt_or_free(engine,monkeypatch):
    store,m,p,scenes=engine;calls=[]
    monkeypatch.setattr(m['production'],'resources',lambda:{'disk_free':100*1024**3})
    def handler(request):
        calls.append((request.method,request.url.path));return httpx.Response(200,json={'queue_running':[[0,'foreign',{},{}]],'queue_pending':[]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await m['production'].Dispatcher().available(client,{})
    assert 'outside this studio' in asyncio.run(run())
    assert calls==[('GET','/queue')]


def test_out_of_order_collection_and_partial_batch_recovery(engine):
    import io
    store,m,p,scenes=engine
    store.update_project(p['id'],1,{'settings':{'width':64,'height':64}})
    m['production'].produce(p['id'],'stills');jobs=store.all('SELECT * FROM jobs ORDER BY created')
    images={}
    for name,color in [('a.png','red'),('b.png','blue'),('b2.png','green')]:
        buffer=io.BytesIO();Image.new('RGB',(64,64),color).save(buffer,format='PNG');images[name]=buffer.getvalue()
    def handler(request):return httpx.Response(200,content=images[request.url.params['filename']])
    def result(names):return {'outputs':{'save':{'images':[{'filename':name,'subfolder':'sceneflow/exact','type':'output'} for name in names]}}}
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            b={**jobs[1],'comfy_prompt_id':'backend-b'};a={**jobs[0],'comfy_prompt_id':'backend-a'}
            entry=json.loads(b['snapshot'])['workflow_definition']
            first=await m['media'].collect_outputs(client,b,result(['b.png']),entry)
            full=await m['media'].collect_outputs(client,b,result(['b.png','b2.png']),entry)
            again=await m['media'].collect_outputs(client,b,result(['b.png','b2.png']),entry)
            only_a=await m['media'].collect_outputs(client,a,result(['a.png']),entry)
            assert len(first)==1 and len(full)==len(again)==2 and len(only_a)==1
            assert {x['id'] for x in full}=={x['id'] for x in again}
            assert all(x['scene_id']==b['scene_id'] for x in full) and only_a[0]['scene_id']==a['scene_id']
            with Image.open(m['media'].asset_path(only_a[0]['id'])) as image:assert image.getpixel((32,32))==(255,0,0)
    asyncio.run(run())


def test_individual_generation_preserves_background_automatic_run(engine):
    store,m,p,scenes=engine;m['production'].produce(p['id'],'all')
    assert m['production'].state(p['id'])['auto_run']==1
    m['production'].produce(p['id'],'selected_still',scenes[0]['id'])
    assert m['production'].state(p['id'])['auto_run']==1


def test_failed_bulk_job_can_be_explicitly_replanned_without_unique_key_error(engine):
    store,m,p,scenes=engine;m['production'].produce(p['id'],'stills')
    old=store.one('SELECT * FROM jobs WHERE scene_id=?',(scenes[0]['id'],));m['production'].update_job(old['id'],'failed')
    m['production'].produce(p['id'],'stills')
    jobs=store.all('SELECT * FROM jobs WHERE scene_id=?',(scenes[0]['id'],))
    assert len(jobs)==2 and len({j['request_key'] for j in jobs})==2


def test_automatic_resume_reuses_completed_manual_still(engine):
    store,m,p,scenes=engine
    manual=store.update_project(p['id'],1,{'mode':'manual','settings':{'auto_export':False}})
    m['production'].produce(p['id'],'selected_still',scenes[0]['id'])
    job=store.one('SELECT * FROM jobs WHERE scene_id=?',(scenes[0]['id'],));aid=uid();relative='projects/'+p['id']+'/'+aid+'.png';path=m['media'].ROOT/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
    store.execute('INSERT INTO assets(id,project_id,scene_id,job_id,kind,path,sha256,metadata) VALUES(?,?,?,?,?,?,?,?)',(aid,p['id'],scenes[0]['id'],job['id'],'image',relative,'hash','{}'))
    asyncio.run(m['production'].Dispatcher().complete(job,[store.one('SELECT * FROM assets WHERE id=?',(aid,))]))
    assert not store.scene(scenes[0]['id'])['selected_image_id']
    store.update_project(p['id'],manual['revision'],{'mode':'automatic'})
    asyncio.run(m['production'].Dispatcher().reuse_completed(p['id']));m['production'].produce(p['id'],'all')
    assert store.scene(scenes[0]['id'])['selected_image_id']==aid
    assert store.one("SELECT COUNT(*) n FROM jobs WHERE scene_id=? AND kind='image'",(scenes[0]['id'],))['n']==1
    assert store.one("SELECT COUNT(*) n FROM jobs WHERE scene_id=? AND kind='video'",(scenes[0]['id'],))['n']==1


def test_image_review_gate_cannot_be_bypassed_by_reclicking_auto_produce(engine):
    store,m,p,scenes=engine;aid=uid();relative='projects/'+p['id']+'/'+aid+'.png';path=m['media'].ROOT/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture')
    store.execute('INSERT INTO assets(id,project_id,scene_id,kind,path,sha256,metadata) VALUES(?,?,?,?,?,?,?)',(aid,p['id'],scenes[0]['id'],'image',relative,'hash','{}'))
    store.execute('UPDATE scenes SET selected_image_id=? WHERE id=?',(aid,scenes[0]['id']))
    m['production'].produce(p['id'],'all')
    video=store.one("SELECT * FROM jobs WHERE scene_id=? AND kind='video'",(scenes[0]['id'],))
    assert video['status']=='awaiting_review'
    m['production'].approve_and_continue(aid)
    assert store.one('SELECT status FROM jobs WHERE id=?',(video['id'],))['status']=='queued'
    assert store.one("SELECT COUNT(*) n FROM jobs WHERE scene_id=? AND kind='video'",(scenes[0]['id'],))['n']==1


def test_imported_media_inputs_require_explicit_owned_source_mapping():
    from studio.adapters import validate_media_mappings
    entry={'task':'image_to_video','graph':{'source':{'class_type':'LoadImage','inputs':{'image':'shared.png'}}},'mappings':{'source_image':{'node':'source','input':'image'}}}
    assert validate_media_mappings(entry)==[]
    assert validate_media_mappings({**entry,'task':'text_to_image'})
    assert validate_media_mappings({**entry,'mappings':{}})
    assert validate_media_mappings({**entry,'graph':{**entry['graph'],'audio':{'class_type':'LoadAudio','inputs':{}}}})
