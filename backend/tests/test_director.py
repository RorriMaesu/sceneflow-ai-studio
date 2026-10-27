import asyncio
import importlib
import json

import httpx
import pytest

from studio.store import Conflict,Store


@pytest.fixture
def director(tmp_path,monkeypatch):
    module=importlib.import_module('studio.director')
    store=Store(tmp_path/'director.sqlite')
    monkeypatch.setattr(module,'db',store)
    monkeypatch.setattr(importlib.import_module('studio.production'),'supersede_pending',lambda _:None)
    module.migrate()
    project=store.create_project('A film')
    a=store.add_scene(project['id'],'A',{'image_prompt':'first image','video_prompt':'first motion'})
    b=store.add_scene(project['id'],'B',{'image_prompt':'second image','video_prompt':'second motion'})
    return module,store,store.project(project['id']),a,b


def test_typed_actions_apply_atomically_and_only_once(director):
    m,store,p,a,b=director
    body={'reply':'Two edits','actions':[{'action':'revise_scene','scene_id':a['id'],'image_prompt':'new first image'},{'action':'revise_scene','scene_id':b['id'],'video_prompt':'new second motion'}]}
    pid=m.add_proposal(p,'job','director',body)
    store.update_scene(b['id'],1,body={'video_prompt':'manual edit wins'})
    with pytest.raises(Conflict):
        m.apply_proposal(pid)
    assert store.scene(a['id'])['revision']==1
    assert store.one('SELECT status FROM proposals WHERE id=?',(pid,))['status']=='pending'
    fresh=store.project(p['id']);pid=m.add_proposal(fresh,'job','director',body)
    m.apply_proposal(pid)
    assert store.scene(a['id'])['revision']==2
    with pytest.raises(Conflict):
        m.apply_proposal(pid)


def test_foreign_scene_action_cannot_partially_apply(director):
    m,store,p,a,b=director
    body={'reply':'Invalid scope','actions':[{'action':'revise_scene','scene_id':a['id'],'image_prompt':'must not apply'},{'action':'revise_scene','scene_id':'foreign','image_prompt':'bad'}]}
    pid=m.add_proposal(p,'job','director',body)
    with pytest.raises(Conflict):m.apply_proposal(pid)
    assert store.scene(a['id'])['revision']==1


def test_structured_output_repairs_once_then_fails_without_mutation(director):
    m,store,p,_,_=director
    calls=[]
    def handler(request):
        calls.append(json.loads(request.content))
        content='invalid' if len(calls)==1 else json.dumps({'reply':'Recovered','actions':[]})
        return httpx.Response(200,json={'message':{'content':content}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            return await m.structured(c,'local',[{'role':'user','content':'hello'}],m.DirectorReply)
    assert asyncio.run(run()).reply=='Recovered'
    assert len(calls)==2 and store.project(p['id'])['revision']==1
    def invalid(_):return httpx.Response(200,json={'message':{'content':'invalid'}})
    async def fail():
        async with httpx.AsyncClient(transport=httpx.MockTransport(invalid)) as c:
            await m.structured(c,'local',[],m.DirectorReply)
    with pytest.raises(ValueError,match='twice'):asyncio.run(fail())


def test_bounded_context_has_one_detailed_scene(director):
    m,_,p,a,b=director
    for s in p['scenes']:
        s['body']['image_prompt']='x'*6000
    value=m.context(p,b['id'])
    assert len(value['selected_scenes'])==1
    assert value['selected_scenes'][0]['id']==b['id']
    assert len(json.dumps(value))<12000


def test_duration_seed_edits_and_reviewed_command_are_saved_atomically(director,monkeypatch):
    m,store,p,a,b=director
    store.execute("INSERT INTO jobs(id,project_id,kind,status,snapshot,dependencies) VALUES(?,?,?,?,?,'[]')",('job',p['id'],'director','completed',json.dumps({'allow_operations':True})))
    body={'reply':'Shorten and regenerate A','actions':[{'action':'revise_scene','scene_id':a['id'],'duration':2,'seed':77},{'action':'regenerate_still','scene_id':a['id']}]}
    identifier=m.add_proposal(p,'job','director',body);m.apply_proposal(identifier)
    updated=store.scene(a['id']);assert updated['body']['duration']==2 and updated['body']['seed']==77
    command=store.one('SELECT * FROM director_commands');assert command['target_revision']==updated['revision'] and command['status']=='pending'
    seen=[]
    production=importlib.import_module('studio.production');monkeypatch.setattr(production,'produce',lambda pid,scope,sid:seen.append((pid,scope,sid)))
    registry=importlib.import_module('studio.adapters').registry;monkeypatch.setattr(registry,'info',{'ready':{}})
    asyncio.run(m.run_commands())
    assert seen==[(p['id'],'selected_still',a['id'])]
    assert store.one('SELECT status FROM director_commands')['status']=='completed'
    asyncio.run(m.run_commands());assert len(seen)==1


def test_approved_command_rejects_later_project_setting_changes(director):
    m,store,p,a,b=director
    store.execute("INSERT INTO jobs(id,project_id,kind,status,snapshot,dependencies) VALUES(?,?,?,?,?,'[]')",('job',p['id'],'director','completed',json.dumps({'allow_operations':True})))
    identifier=m.add_proposal(p,'job','director',{'reply':'Regenerate A','actions':[{'action':'regenerate_still','scene_id':a['id']}]});current=m.apply_proposal(identifier)
    store.update_project(p['id'],current['revision'],{'settings':{'image_steps':25}})
    asyncio.run(m.run_commands())
    assert store.one('SELECT status FROM director_commands')['status']=='failed'
    assert all(job['kind']=='director' for job in store.jobs(p['id']))


def test_setting_edits_cannot_be_disguised_as_generation_commands(director):
    m,store,p,a,b=director
    with pytest.raises(ValueError,match='cannot carry'):
        m.DirectorAction(action='regenerate_video',scene_id=a['id'],duration=1.5,seed=773)
    with pytest.raises(ValueError):m.CreativeReply(reply='Wrong operation',actions=[{'action':'regenerate_video','scene_id':a['id']}])
    identifier=m.add_proposal(p,'unapproved-command-job','director',{'reply':'Wrong operation','actions':[{'action':'regenerate_video','scene_id':a['id']}]})
    with pytest.raises(ValueError,match='creative edits only'):m.apply_proposal(identifier)
    assert not store.all('SELECT * FROM director_commands') and store.project(p['id'])['revision']==p['revision']
