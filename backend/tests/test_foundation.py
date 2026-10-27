import importlib

import pytest
from fastapi.testclient import TestClient

from studio.config import private
from studio.store import Store


@pytest.fixture
def connected(tmp_path, monkeypatch):
    application = importlib.import_module('studio.app')
    security = importlib.import_module('studio.security')
    store = Store(tmp_path / 'test.sqlite')
    monkeypatch.setattr(application, 'db', store)
    monkeypatch.setattr(security, 'db', store)
    for name in ['production','media','exports','adapters','routes_production','director','routes_director','routes_editing','editing_export','bundles','quality','diagnostics','continuity','insights','storage','model_library','routes_setup']:
        module=importlib.import_module('studio.'+name)
        monkeypatch.setattr(module,'db',store)
    importlib.import_module('studio.production').migrate()
    security.failures.clear()
    client = TestClient(application.app, base_url='http://127.0.0.1:8770')
    origin = 'http://127.0.0.1:8770'
    response = client.post('/api/pair', json={'code': private['pair_code']}, headers={'Origin': origin})
    assert response.status_code == 200
    headers = {'Authorization': 'Bearer '+response.json()['token'], 'Origin': origin}
    return client, headers, store


def test_private_operations_require_pairing(connected):
    client, _, _ = connected
    assert client.get('/api/projects').status_code == 401


def test_hostile_origin_cannot_pair_or_mutate(connected):
    client, headers, _ = connected
    headers = {**headers, 'Origin': 'https://evil.example'}
    assert client.post('/api/projects', json={'title': 'intrusion'}, headers=headers).status_code == 403
    assert client.post('/api/pair', json={'code': private['pair_code']}, headers={'Origin': 'https://evil.example'}).status_code == 403


def test_host_header_rejected(connected):
    client, headers, _ = connected
    assert client.get('/api/projects', headers={**headers, 'Host': 'evil.example'}).status_code == 400


def test_project_persists_after_database_reopen(connected):
    client, headers, store = connected
    p = client.post('/api/projects', json={'title': 'A new film', 'brief': 'Moonlight'}, headers=headers).json()
    assert p['mode'] == 'hybrid'
    assert p['settings']['qa_enabled'] is False
    assert Store(store.path).project(p['id'])['title'] == 'A new film'


@pytest.mark.parametrize('shape,dimensions',[('landscape',(1920,1080)),('portrait',(1080,1920)),('square',(1080,1080))])
def test_new_video_shape_is_initialized_without_saving_an_empty_edit(connected,shape,dimensions):
    client,headers,store=connected
    response=client.post('/api/projects',json={'title':'New video','settings':{'video_shape':shape}},headers=headers)
    assert response.status_code==200
    p=response.json();assert not p['timeline']['clips']
    assert (p['timeline']['settings']['width'],p['timeline']['settings']['height'])==dimensions
    assert p['timeline']['revision']==1 and store.project(p['id'])['settings']['paused']


def test_scene_revisions_are_immutable_and_conflicts_are_explicit(connected):
    client, headers, store = connected
    p = client.post('/api/projects', json={'title': 'Test'}, headers=headers).json()
    s = client.post(f"/api/projects/{p['id']}/scenes", json={'title': 'Opening', 'body': {'image_prompt': 'old'}}, headers=headers).json()
    response = client.patch('/api/scenes/'+s['id'], json={'revision': 1, 'body': {'image_prompt': 'new'}}, headers=headers)
    assert response.status_code == 200
    assert response.json()['revision_id'] != s['revision_id']
    conflict = client.patch('/api/scenes/'+s['id'], json={'revision': 1, 'title': 'Lost update'}, headers=headers)
    assert conflict.status_code == 409
    assert 'old' in store.one('SELECT body FROM scene_revisions WHERE id=?', (s['revision_id'],))['body']


def test_projects_and_scenes_do_not_cross(connected):
    client, headers, _ = connected
    projects = [client.post('/api/projects', json={'title': name}, headers=headers).json() for name in ['A', 'B']]
    for p in projects:
        client.post(f"/api/projects/{p['id']}/scenes", json={'title': p['title'], 'body': {'image_prompt': p['title']}}, headers=headers)
    for p in projects:
        scenes = client.get('/api/projects/'+p['id'], headers=headers).json()['scenes']
        assert len(scenes) == 1
        assert scenes[0]['body']['image_prompt'] == p['title']


def test_session_revocation(connected):
    client, headers, _ = connected
    assert client.post('/api/session/revoke', headers=headers).status_code == 200
    assert client.get('/api/projects', headers=headers).status_code == 401


def test_pair_code_is_consumed(connected):
    client, _, _ = connected
    code = private['pair_code']
    assert client.post('/api/pair', json={'code': code}).status_code == 200
    assert client.post('/api/pair', json={'code': code}).status_code == 401


def test_service_urls_cannot_be_public_or_include_credentials(connected):
    client, headers, _ = connected
    for value in ['https://example.com', 'http://127.0.0.1@evil.example', 'http://127.0.0.1/secret']:
        assert client.patch('/api/settings', json={'comfy_url': value}, headers=headers).status_code == 422


def test_event_tickets_require_authentication(connected):
    client, headers, _ = connected
    assert client.post('/api/events/ticket').status_code == 401
    assert len(client.post('/api/events/ticket', headers=headers).json()['ticket']) > 20


def test_media_ranges_are_scoped_and_revoked(connected):
    import io
    from PIL import Image
    client,headers,store=connected
    p=client.post('/api/projects',json={'title':'Media security'},headers=headers).json()
    s=client.post(f"/api/projects/{p['id']}/scenes",json={'title':'A'},headers=headers).json()
    image=io.BytesIO();Image.new('RGB',(64,64),'red').save(image,format='PNG')
    assets=[]
    for _ in range(2):assets.append(client.post('/api/scenes/'+s['id']+'/import',files={'file':('still.png',image.getvalue(),'image/png')},headers=headers).json()['asset_id'])
    ticket=client.post('/api/assets/'+assets[0]+'/ticket',headers=headers).json()['url']
    response=client.get(ticket,headers={'Origin':headers['Origin'],'Range':'bytes=0-15'})
    assert response.status_code==206 and len(response.content)==16
    assert response.headers['content-range'].startswith('bytes 0-15/')
    assert client.get(ticket.replace(assets[0],assets[1]),headers={'Origin':headers['Origin']}).status_code==401
    client.post('/api/session/revoke',headers=headers)
    assert client.get(ticket,headers={'Origin':headers['Origin']}).status_code==403


def test_video_download_is_an_attachment_scoped_to_asset_and_live_session(connected,tmp_path,monkeypatch):
    from studio import media
    from studio.store import uid
    client,headers,store=connected;monkeypatch.setattr(media,'ROOT',tmp_path)
    p=store.create_project('A video: safe/name');folder=tmp_path/'projects'/p['id'];folder.mkdir(parents=True)
    file=folder/'video.mp4';file.write_bytes(b'download-boundary-test')
    ids=[uid(),uid()]
    for identifier in ids:store.execute('INSERT INTO assets(id,project_id,kind,path,metadata) VALUES(?,?,?,?,?)',(identifier,p['id'],'export',str(file.relative_to(tmp_path)),'{}'))
    assert client.post('/api/assets/'+ids[0]+'/download-ticket').status_code==401
    url=client.post('/api/assets/'+ids[0]+'/download-ticket',headers=headers).json()['url']
    response=client.get(url,headers={'Origin':headers['Origin']})
    assert response.status_code==200 and response.content==file.read_bytes()
    assert 'attachment;' in response.headers['content-disposition'] and 'safe/name' not in response.headers['content-disposition']
    assert client.get(url.replace(ids[0],ids[1]),headers={'Origin':headers['Origin']}).status_code==401
    media_url=client.post('/api/assets/'+ids[0]+'/ticket',headers=headers).json()['url']
    assert client.get(media_url.replace('/media/','/downloads/'),headers={'Origin':headers['Origin']}).status_code==401
    client.post('/api/session/revoke',headers=headers)
    assert client.get(url,headers={'Origin':headers['Origin']}).status_code==403


def test_show_in_folder_accepts_only_registered_exports(connected,tmp_path,monkeypatch):
    import os,subprocess
    from studio import media
    from studio.store import uid
    client,headers,store=connected;monkeypatch.setattr(media,'ROOT',tmp_path)
    p=store.create_project('Reveal');folder=tmp_path/'projects'/p['id'];folder.mkdir(parents=True)
    file=folder/'video.mp4';file.write_bytes(b'owned file');identifier=uid()
    store.execute('INSERT INTO assets(id,project_id,kind,path,metadata) VALUES(?,?,?,?,?)',(identifier,p['id'],'export',str(file.relative_to(tmp_path)),'{}'))
    calls=[];monkeypatch.setattr(subprocess,'Popen',lambda args,**kwargs:calls.append((args,kwargs)))
    assert client.post('/api/assets/'+identifier+'/reveal').status_code==401
    assert client.post('/api/assets/unknown/reveal',headers=headers).status_code==422
    response=client.post('/api/assets/'+identifier+'/reveal',headers=headers)
    assert response.status_code==(200 if os.name=='nt' else 422)
    if os.name=='nt':assert calls[0][0]==['explorer.exe','/select,',str(file)]
    else:assert not calls


def test_existing_websocket_closes_after_session_revocation(connected):
    from starlette.websockets import WebSocketDisconnect
    client,headers,store=connected
    value=client.post('/api/events/ticket',headers=headers).json()['ticket']
    with client.websocket_connect('ws://127.0.0.1:8770/ws?ticket='+value,headers={'Origin':headers['Origin']}) as socket:
        socket.receive_json()
        client.post('/api/session/revoke',headers=headers)
        with pytest.raises(WebSocketDisconnect):
            for _ in range(10):socket.receive_json()


def test_invalid_project_settings_are_rejected_before_commit(connected):
    client,headers,store=connected
    p=client.post('/api/projects',json={'title':'Validation'},headers=headers).json()
    for setting in [{'candidates':1000},{'qa_threshold':-1},{'max_retries':100},{'gates':{'unknown':True}}]:
        response=client.patch('/api/projects/'+p['id'],json={'revision':1,'settings':setting},headers=headers)
        assert response.status_code==422
        assert store.project(p['id'])['revision']==1


@pytest.mark.parametrize('owns_prompt',[True,False])
def test_targeted_cancel_never_interrupts_a_foreign_prompt(connected,monkeypatch,owns_prompt):
    import httpx,json
    from studio.store import uid
    client,headers,store=connected
    p=store.create_project('Cancel scope');s=store.add_scene(p['id'],'A');identifier=uid();prompt=uid()
    store.execute('INSERT INTO jobs(id,project_id,scene_id,kind,status,snapshot,dependencies,comfy_prompt_id) VALUES(?,?,?,?,?,?,?,?)',(identifier,p['id'],s['id'],'video','submitted','{}','[]',prompt))
    calls=[]
    def handler(request):
        calls.append((request.method,request.url.path))
        if request.method=='GET':return httpx.Response(200,json={'queue_running':[[0,prompt,{}, {'sceneflow':{'job_id':identifier if owns_prompt else 'foreign'}}]],'queue_pending':[]})
        return httpx.Response(200,json={'cancelled':True})
    factory=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kwargs:factory(transport=httpx.MockTransport(handler),**kwargs))
    response=client.post('/api/jobs/'+identifier+'/cancel',headers=headers)
    assert response.status_code==(200 if owns_prompt else 409)
    assert calls==[('GET','/queue')]+([('POST','/api/jobs/'+prompt+'/cancel')] if owns_prompt else [])
    assert store.one('SELECT cancel_requested FROM jobs WHERE id=?',(identifier,))['cancel_requested']==int(owns_prompt)
