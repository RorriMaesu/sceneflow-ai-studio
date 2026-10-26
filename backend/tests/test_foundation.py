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
    for name in ['production','media','exports','adapters','routes_production','director','routes_director','routes_editing','editing_export','bundles']:
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
