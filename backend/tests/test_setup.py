import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

from .test_foundation import connected
from studio import model_library as models, storage
from studio.store import encode, now


@pytest.fixture
def library(connected, tmp_path, monkeypatch):
    client, headers, db = connected
    folder = tmp_path / 'chosen'
    folder.mkdir()
    root = storage.grant(folder)
    storage.use_routes({role: root['id'] for role in storage.ROLES})
    monkeypatch.setitem(storage.settings, 'disk_reserve_gb', 0.001)
    payload = b'verified-model-test'
    value = {'id': 'fixture', 'name': 'Test voices', 'repo': 'official/test', 'revision': 'a' * 40,
             'license': 'test', 'source': 'https://huggingface.co/official/test', 'gated': False,
             'files': [{'path': 'model.safetensors', 'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}]}
    monkeypatch.setattr(models, 'catalog', lambda: [value])
    return client, headers, db, root, value, payload


def session(db):
    return db.one('SELECT * FROM sessions ORDER BY created DESC LIMIT 1')


def test_setup_requires_pairing_and_no_browser_path_grants(connected):
    client, headers, _ = connected
    assert client.get('/api/setup').status_code == 401
    assert client.post('/api/setup/folders/routes', json={'routes': {'models': 'C:/'}}, headers=headers).status_code == 422
    assert client.post('/api/setup/folders/routes', json={'routes': {}, 'path': 'C:/'}, headers=headers).status_code == 422


def test_routes_reject_unknown_category_and_missing_drive(library, monkeypatch):
    _, _, _, root, _, _ = library
    with pytest.raises(ValueError): storage.use_routes({'other': root['id']})
    monkeypatch.setattr(storage, 'identity', lambda _: 'different-drive')
    with pytest.raises(ValueError, match='missing or changed'): storage.checked_root(root['id'])


@pytest.mark.parametrize('value', ['../escape', '/absolute', 'C:/escape', 'safe/../../escape', 'safe:stream', 'safe\x00bad'])
def test_storage_boundaries(library, value):
    with pytest.raises(ValueError): storage.child(library[3]['id'], value, True)


def test_new_media_uses_selected_root_without_relocating_old_media(library):
    from studio import media
    _, _, db, root, _, _ = library
    project = db.create_project('Folder test')
    relative, destination = storage.media_location(project['id'], None, 'audio', 'take', '.wav', {'role': 'voiceover'})
    assert relative.startswith('@' + root['id'] + '/')
    assert media.managed_path(relative) == destination
    assert 'speech' in str(destination)
    assert media.managed_path(Path('projects') / project['id'] / 'original.wav').is_relative_to(media.ROOT / 'projects')


def test_quote_is_bound_to_session_manifest_and_reviewed_folder(library):
    _, _, db, root, value, _ = library
    user = session(db)
    quote = models.quote_install('fixture', user)
    assert quote['download_bytes'] == value['files'][0]['bytes']
    with pytest.raises(ValueError): models.start_download(quote['id'], {'hash': 'another-session'})
    value['revision'] = 'b' * 40
    with pytest.raises(ValueError, match='changed'): models.start_download(quote['id'], user)
    assert not db.all('SELECT * FROM model_downloads')


def test_disk_full_prevents_download(library, monkeypatch):
    _, _, db, _, _, _ = library
    monkeypatch.setattr(storage.shutil, 'disk_usage', lambda _: type('Space', (), {'free': 1})())
    with pytest.raises(ValueError, match='Not enough space'): models.quote_install('fixture', session(db))


def test_verified_download_and_duplicate_request(library, monkeypatch):
    client, headers, db, root, value, payload = library
    user = session(db)
    quote = models.quote_install('fixture', user)
    denied = client.post('/api/setup/downloads', json={'quote_id': quote['id']}, headers=headers)
    assert denied.status_code == 422
    row = models.start_download(quote['id'], user)
    quote2 = models.quote_install('fixture', user)
    assert models.start_download(quote2['id'], user)['id'] == row['id']
    factory = models.httpx.AsyncClient
    monkeypatch.setattr(models.httpx, 'AsyncClient', lambda **kwargs: factory(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=payload))))
    asyncio.run(models.manager.execute(row))
    assert db.one('SELECT status FROM model_downloads WHERE id=?', (row['id'],))['status'] == 'completed'
    assert models.file_path(value, root['id'], value['files'][0]).read_bytes() == payload
    assert models.list_packs()[0]['state'] == 'needs_test'


def test_corrupt_model_is_never_installed(library, monkeypatch):
    _, _, db, _, _, payload = library
    row = models.start_download(models.quote_install('fixture', session(db))['id'], session(db))
    factory = models.httpx.AsyncClient
    monkeypatch.setattr(models.httpx, 'AsyncClient', lambda **kwargs: factory(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=b'x' * len(payload)))))
    with pytest.raises(ValueError, match='verification'): asyncio.run(models.manager.execute(row))
    assert not db.all('SELECT * FROM model_installs')


def test_partial_download_resumes_only_the_pinned_content(library, monkeypatch):
    _, _, db, root, value, payload = library
    row = models.start_download(models.quote_install('fixture', session(db))['id'], session(db))
    item = value['files'][0]
    path = models.file_path(value, root['id'], item).with_name(item['path'] + '.part')
    path.write_bytes(payload[:4])
    descriptor = {'revision': value['revision'], 'path': item['path'], 'bytes': item['bytes'], 'sha256': item['sha256'], 'git_blob_sha1': None}
    path.with_name(path.name + '.json').write_text(encode(descriptor))
    def reply(request):
        assert request.headers['range'] == 'bytes=4-'
        return httpx.Response(206, content=payload[4:], headers={'Content-Range': f'bytes 4-{len(payload)-1}/{len(payload)}'})
    factory = models.httpx.AsyncClient
    monkeypatch.setattr(models.httpx, 'AsyncClient', lambda **kwargs: factory(transport=httpx.MockTransport(reply)))
    asyncio.run(models.manager.execute(row))
    assert models.file_path(value, root['id'], item).read_bytes() == payload


def test_revoked_session_pauses_before_network(library):
    _, _, db, _, _, _ = library
    user = session(db)
    row = models.start_download(models.quote_install('fixture', user)['id'], user)
    db.execute('DELETE FROM sessions WHERE hash=?', (user['hash'],))
    with pytest.raises(models.DownloadPaused): asyncio.run(models.manager.execute(row))


def test_cache_environment_is_offline_and_uses_selected_folder(library):
    environment = storage.worker_environment()
    assert str(Path(library[3]['path'])) in environment['HF_HOME']
    assert environment['HF_HUB_OFFLINE'] == '1'
    assert environment['TRANSFORMERS_OFFLINE'] == '1'


def test_corrupt_existing_bytes_are_included_in_the_download_review(library):
    _, _, db, root, value, payload = library
    models.file_path(value, root['id'], value['files'][0]).write_bytes(b'x' * len(payload))
    assert models.quote_install('fixture', session(db))['download_bytes'] == len(payload)


def test_selected_media_and_backup_folders_remain_discoverable(library, tmp_path):
    from PIL import Image
    from studio import media, bundles
    _, _, db, root, _, _ = library
    project = db.create_project('External media backup')
    scene = db.add_scene(project['id'], 'Opening')
    incoming = tmp_path / 'picture.png'
    Image.new('RGB', (64, 64), 'red').save(incoming)
    asset = media.add_asset(project['id'], scene['id'], None, 'image', incoming)
    assert asset['path'].startswith('@' + root['id'])
    backup = bundles.create_bundle(project['id'])
    assert storage.backup_file(backup['id']).is_file()
    assert media.asset_path(asset['id']).is_file()


def test_export_scratch_stays_with_its_original_folder(library, tmp_path):
    old = storage.export_folder('persistent-task')
    other = tmp_path / 'another-drive-folder'
    other.mkdir()
    root = storage.grant(other)
    storage.use_routes({'cache': root['id']})
    assert storage.export_folder('persistent-task') == old
    assert storage.export_folder('new-task').is_relative_to(other)
