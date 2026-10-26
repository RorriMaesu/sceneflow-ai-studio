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
