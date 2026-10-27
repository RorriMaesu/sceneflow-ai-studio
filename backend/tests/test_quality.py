import asyncio
import importlib
import json

import pytest
from PIL import Image

from studio.store import Store,encode,now,uid


@pytest.fixture
def quality(tmp_path,monkeypatch):
    store=Store(tmp_path/'quality.sqlite');modules={n:importlib.import_module('studio.'+n) for n in ['quality','media','production','storage']}
    for module in modules.values():
        monkeypatch.setattr(module,'db',store)
        if hasattr(module,'ROOT'):monkeypatch.setattr(module,'ROOT',tmp_path)
    for name in ['temp','projects']:(tmp_path/name).mkdir()
    modules['production'].migrate();p=store.create_project('QA test');s=store.add_scene(p['id'],'A',{'image_prompt':'A red lantern on a desk','video_prompt':'The light flickers gently'})
    snapshot={'project_id':p['id'],'scene_id':s['id'],'scene_revision_id':s['revision_id'],'workflow_id':'test','positive_prompt':s['body']['image_prompt'],'image_prompt':s['body']['image_prompt'],'video_prompt':s['body']['video_prompt'],'seed':1,'config':p['settings']}
    job=modules['production'].queue_snapshot('image',snapshot);incoming=tmp_path/'temp'/'image.png';Image.new('RGB',(64,64),(80,20,10)).save(incoming)
    asset=modules['media'].add_asset(p['id'],s['id'],job['id'],'image',incoming,extra={'scene_revision_id':s['revision_id']})
    monkeypatch.setattr(modules['production'].registry,'verified',lambda *args:None)
    return store,modules,p,s,job,asset


def test_disabled_qa_never_calls_local_model(quality,monkeypatch):
    store,m,p,s,job,asset=quality
    async def forbidden(*args,**kwargs):raise AssertionError('QA must be skipped when disabled')
    monkeypatch.setattr(m['quality'],'queue_review',forbidden)
    asyncio.run(m['production'].Dispatcher().complete(job,[asset]))
    assert store.one('SELECT status FROM jobs WHERE id=?',(job['id'],))['status']=='completed'
    assert not store.all("SELECT * FROM jobs WHERE kind='qa'")


def test_manual_approval_wins_over_failed_visual_review(quality):
    store,m,p,s,job,asset=quality;m['media'].select_asset(asset['id'],True)
    snapshot={'allow_actions':True,'scene_revision_id':s['revision_id'],'asset_id':asset['id'],'qa_policy':{'qa_regenerate':True,'max_retries':2}}
    result={'recommendation':'regenerate','overall_score':.1,'issues':[{'severity':'high','description':'wrong prop'}]}
    asyncio.run(m['quality'].apply_result(asset,{},snapshot,result))
    assert len(store.jobs(p['id']))==1
    assert store.scene(s['id'])['selected_image_id']==asset['id']
    assert store.one('SELECT approval_source FROM assets WHERE id=?',(asset['id'],))['approval_source']=='user'


def test_quality_retries_stop_at_two_and_stop_without_improvement(quality):
    store,m,p,s,job,asset=quality;snapshot={'asset_id':asset['id'],'scene_revision_id':s['revision_id'],'qa_policy':{'qa_regenerate':True,'max_retries':2}}
    assert m['quality'].retry_allowed(store,job,snapshot,.3)
    frozen=json.loads(job['snapshot']);frozen['quality_retry']=1
    m['production'].queue_snapshot('image',frozen,force=True)
    prior_id=uid();store.execute('INSERT INTO assets(id,project_id,scene_id,kind,metadata) VALUES(?,?,?,?,?)',(prior_id,p['id'],s['id'],'image','{}'))
    store.execute('INSERT INTO qa VALUES(?,?,?,?,?)',(uid(),prior_id,'vision',encode({'asset_id':prior_id,'scene_revision_id':s['revision_id'],'overall_score':.5}),now()))
    assert not m['quality'].retry_allowed(store,job,snapshot,.4)
    assert m['quality'].retry_allowed(store,job,snapshot,.6)
    frozen['quality_retry']=2;m['production'].queue_snapshot('image',frozen,force=True)
    assert not m['quality'].retry_allowed(store,job,snapshot,.9)


def test_text_only_model_rejected_before_vision_inference(quality,monkeypatch):
    store,m,p,s,job,asset=quality
    async def details(*args,**kwargs):return {'capabilities':['completion']}
    monkeypatch.setattr(m['quality'],'model_details',details)
    with pytest.raises(ValueError,match='vision support'):
        asyncio.run(m['quality'].queue_review(asset['id'],'text-only'))
    assert not store.all("SELECT * FROM jobs WHERE kind='qa'")


def test_actionable_low_score_preserves_asset_and_queues_new_frozen_attempt(quality):
    store,m,p,s,job,asset=quality
    store.update_project(p['id'],1,{'mode':'automatic','settings':{'qa_enabled':True,'qa_regenerate':True}})
    frozen=json.loads(job['snapshot']);frozen.update(seed=s['body']['seed'],base_seed=s['body']['seed'],workflow_id=p['settings']['image_workflow'],negative_prompt='',width=640,height=352,image_steps=12)
    store.execute("UPDATE jobs SET snapshot=?,status='completed' WHERE id=?",(encode(frozen),job['id']))
    snapshot={'allow_actions':True,'asset_id':asset['id'],'scene_revision_id':s['revision_id'],'qa_policy':{'qa_regenerate':True,'max_retries':2,'qa_threshold':.7}}
    asyncio.run(m['quality'].apply_result(asset,{},snapshot,{'recommendation':'regenerate','overall_score':.2,'issues':[{'severity':'high','description':'Requested subject is missing'}]}))
    jobs=store.jobs(p['id']);retry=next(j for j in jobs if j['id']!=job['id'])
    assert len(jobs)==2 and retry['snapshot']['quality_retry']==1
    assert retry['snapshot']['positive_prompt']==frozen['positive_prompt'] and retry['snapshot']['seed']==frozen['seed']+1009
    assert store.one('SELECT sha256 FROM assets WHERE id=?',(asset['id'],))['sha256']==asset['sha256']


def test_conflicting_high_score_does_not_trigger_regeneration(quality):
    store,m,p,s,job,asset=quality
    store.update_project(p['id'],1,{'mode':'automatic','settings':{'qa_enabled':True,'qa_regenerate':True}})
    frozen=json.loads(job['snapshot']);frozen.update(seed=s['body']['seed'],base_seed=s['body']['seed'],workflow_id=p['settings']['image_workflow'],negative_prompt='',width=640,height=352,image_steps=12)
    store.execute("UPDATE jobs SET snapshot=?,status='completed' WHERE id=?",(encode(frozen),job['id']))
    snapshot={'allow_actions':True,'asset_id':asset['id'],'scene_revision_id':s['revision_id'],'qa_policy':{'qa_regenerate':True,'max_retries':2,'qa_threshold':.7}}
    asyncio.run(m['quality'].apply_result(asset,{},snapshot,{'recommendation':'regenerate','overall_score':1,'issues':[{'severity':'high','description':'Conflicting advice'}]}))
    assert len(store.jobs(p['id']))==1


def test_selected_only_qa_keeps_other_candidates_unselected(quality,monkeypatch):
    store,m,p,s,job,asset=quality
    store.update_project(p['id'],1,{'mode':'automatic','settings':{'qa_enabled':True,'qa_auto':True,'qa_image_mode':'selected'}})
    frozen=json.loads(job['snapshot']);frozen.update(seed=s['body']['seed']+1,base_seed=s['body']['seed'],workflow_id=p['settings']['image_workflow'],candidate_index=1,negative_prompt='',width=640,height=352,image_steps=12)
    store.execute('UPDATE jobs SET snapshot=? WHERE id=?',(encode(frozen),job['id']));job=store.one('SELECT * FROM jobs WHERE id=?',(job['id'],))
    async def forbidden(*args,**kwargs):raise AssertionError('Only the chosen candidate should be reviewed automatically')
    monkeypatch.setattr(m['quality'],'queue_review',forbidden)
    asyncio.run(m['production'].Dispatcher().complete(job,[asset]))
    assert not store.scene(s['id'])['selected_image_id']
    assert not store.one('SELECT approved FROM assets WHERE id=?',(asset['id'],))['approved']


def test_acceptance_conflicts_require_human_review(quality):
    _,m,*_=quality
    normalize=m['quality'].consistent_review
    base={'overall_score':1,'recommendation':'accept','issues':[],'confidence':'high','prompt_adherence':1,'visual_quality':1,'character_consistency':1}
    assert normalize(base,{'qa_rubric':'balanced'})['recommendation']=='accept'
    for change in [{'issues':[{'severity':'high','description':'Wrong character'}]},{'confidence':'low'},{'prompt_adherence':.2},{'overall_score':.2}]:
        result=normalize({**base,**change},{'qa_rubric':'balanced'})
        assert result['recommendation']=='review' and result['raw_recommendation']=='accept'
