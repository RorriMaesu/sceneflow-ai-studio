import asyncio
import copy
import importlib
import json

import pytest
from PIL import Image

from studio.store import Store,encode,now,uid


@pytest.fixture
def engine(tmp_path,monkeypatch):
    store=Store(tmp_path/'studio.sqlite')
    modules={name:importlib.import_module('studio.'+name) for name in ['production','adapters','media','exports']}
    for module in modules.values():
        monkeypatch.setattr(module,'db',store)
    modules['production'].migrate()
    from studio.adapters import BUILTINS,DUMMY,qwen_graph,wan_graph,graph_hash
    for original in BUILTINS:
        entry={**original,'status':'ready','reasons':[],'tested':False,'graph':qwen_graph(DUMMY,'test') if original['task']=='text_to_image' else wan_graph(DUMMY,'test','example.png')}
        entry['workflow_hash']=graph_hash(entry['graph'])
        store.execute('INSERT INTO workflow_registry VALUES(?,?,?)',(entry['id'],encode(entry),now()))
    project=store.create_project('Isolation test',mode='hybrid')
    scenes=[store.add_scene(project['id'],'Scene '+str(i),{'image_prompt':'still '+str(i),'video_prompt':'motion '+str(i),'duration':3}) for i in range(20)]
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


def test_missing_backend_does_not_trigger_second_submission(engine):
    store,m,p,scenes=engine
    m['production'].produce(p['id'],'selected_still',scenes[0]['id'])
    job=store.one('SELECT * FROM jobs WHERE scene_id=?',(scenes[0]['id'],))
    m['production'].update_job(job['id'],'reconciling')
    assert store.one('SELECT status FROM jobs WHERE id=?',(job['id'],))['status']=='reconciling'
    assert store.one('SELECT COUNT(*) n FROM jobs')['n']==1
