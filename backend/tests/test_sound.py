import json
import zipfile
import pytest
from .test_foundation import connected
from studio import script_audio as sound, runtime_installer as setup, audio_engine, production
from studio.store import Conflict,encode,now


def test_script_edit_preserves_history_and_rejects_stale_take(connected):
    _,_,db=connected
    project=db.create_project('Script')
    line=sound.save_line(project['id'],{'text':'Before'})
    sound.save_line(project['id'],{'text':'After'},line['id'],line['revision'])
    sound.apply_take({'id':'old-job','project_id':project['id']},{'inputs':{'line_id':line['id'],'line_revision':1}}, {'id':'old-audio'})
    saved=sound.view(project['id'])
    assert saved['lines'][0]['selected_asset_id'] is None
    assert saved['takes'][0]['asset_id']=='old-audio'
    assert json.loads(db.one('SELECT body FROM script_line_revisions')['body'])['text']=='Before'
    with pytest.raises(Conflict):sound.save_line(project['id'],{'text':'Lost edit'},line['id'],1)


def test_cast_and_scene_cannot_cross_productions(connected):
    _,_,db=connected
    a,b=db.create_project('A'),db.create_project('B')
    cast=sound.add_cast(a['id'],'Hero')
    scene=db.add_scene(a['id'],'Opening',{})
    for values in [{'cast_id':cast['id']},{'scene_id':scene['id']}]:
        with pytest.raises(ValueError):sound.save_line(b['id'],{'text':'Wrong production',**values})


def test_runtime_source_archive_cannot_escape_its_folder(tmp_path):
    archive=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('../escaped.txt','bad')
    with pytest.raises(ValueError,match='unsafe'):setup.safe_unzip(archive,tmp_path/'source')
    assert not (tmp_path/'escaped.txt').exists()


def test_setup_sample_runs_while_ordinary_archived_work_waits(connected):
    _,_,db=connected
    audio_engine.migrate()
    project=audio_engine.setup_project()
    probe=production.queue_snapshot('speech',{'project_id':project,'setup_probe':True,'manual_override':True,'manual_requested_at':now()})
    assert production.Dispatcher().next_job()['id']==probe['id']
    db.execute("UPDATE jobs SET snapshot=? WHERE id=?",(encode({'project_id':project,'manual_override':True}),probe['id']))
    assert production.Dispatcher().next_job() is None


def test_sample_download_and_runtime_are_separate_readiness_states(connected,monkeypatch):
    _,_,db=connected
    monkeypatch.setattr(audio_engine,'installed_pack',lambda _:({'revision':'p'}, {}, None))
    monkeypatch.setattr(audio_engine,'runtime_record',lambda _:None)
    with pytest.raises(ValueError,match='program files'):audio_engine.queue_sound(db.create_project('A')['id'],'voices-small',{'text':'Hello'})
    monkeypatch.setattr(audio_engine,'runtime_record',lambda _:{'manifest':'{}'})
    monkeypatch.setattr(audio_engine,'qualification',lambda _:None)
    with pytest.raises(ValueError,match='sample test'):audio_engine.queue_sound(db.create_project('B')['id'],'voices-small',{'text':'Hello'})


def test_small_voice_does_not_silently_ignore_acting_instructions(connected,monkeypatch):
    _,_,db=connected
    monkeypatch.setattr(audio_engine,'installed_pack',lambda _:({'revision':'p'}, {}, None))
    monkeypatch.setattr(audio_engine,'runtime_record',lambda _:{'manifest':'{}'})
    monkeypatch.setattr(audio_engine,'qualification',lambda _:{'body':{}})
    with pytest.raises(ValueError,match='preset delivery'):audio_engine.queue_sound(db.create_project('A')['id'],'voices-small',{'text':'Hello','delivery':'Whisper'})


def test_runtime_quote_cannot_be_approved_by_another_session(connected):
    client,headers,db=connected
    setup.migrate()
    db.execute('INSERT INTO runtime_quotes VALUES(?,?,?,?,0)',('review','someone-else','{}',now()+1000))
    response=client.post('/api/setup/runtimes',json={'quote_id':'review','confirm':True},headers=headers)
    assert response.status_code==422


def test_cancellation_requests_only_the_owned_sound_job(connected):
    client,headers,db=connected
    project=db.create_project('A')
    job=production.queue_snapshot('speech',{'project_id':project['id']})
    db.execute("UPDATE jobs SET status='running' WHERE id=?",(job['id'],))
    response=client.post('/api/jobs/'+job['id']+'/cancel',json={},headers=headers)
    assert response.status_code==200 and db.one('SELECT cancel_requested FROM jobs')['cancel_requested']==1


def test_conversation_timing_uses_recorded_duration_and_preserves_manual_start(connected):
    _,_,db=connected
    p=db.create_project('Conversation')
    first=sound.save_line(p['id'],{'text':'Hello'})
    second=sound.save_line(p['id'],{'text':'Welcome'})
    third=sound.save_line(p['id'],{'text':'Later','start':12})
    for line,duration in [(first,2.4),(second,3.1)]:
        asset='audio-'+line['id']
        db.execute('INSERT INTO assets(id,project_id,kind,metadata,created) VALUES(?,?,?,?,?)',(asset,p['id'],'audio',encode({'duration':duration}),now()))
        sound.apply_take({'id':'job-'+line['id'],'project_id':p['id']},{'inputs':{'line_id':line['id'],'line_revision':1}},{'id':asset})
    rows=sound.view(p['id'])['lines']
    assert rows[0]['start']==0 and rows[1]['start']==pytest.approx(2.65)
    assert rows[2]['start']==12


def test_duplicate_sound_click_reuses_the_same_queued_request(connected):
    _,_,db=connected
    p=db.create_project('A')
    frozen={'project_id':p['id'],'pack_id':'voices-small','inputs':{'text':'Hello'},'manual_requested_at':1}
    first=production.queue_snapshot('speech',frozen)
    second=production.queue_snapshot('speech',{**frozen,'manual_requested_at':2})
    assert first['id']==second['id']


def test_longer_cues_require_a_longer_sample(connected,monkeypatch):
    _,_,db=connected
    monkeypatch.setattr(audio_engine,'installed_pack',lambda _:({'revision':'p'},{},None))
    monkeypatch.setattr(audio_engine,'runtime_record',lambda _:{'manifest':'{}'})
    monkeypatch.setattr(audio_engine,'qualification',lambda _:{'body':{'tested_seconds':3}})
    with pytest.raises(ValueError,match='up to 3 seconds'):
        audio_engine.queue_sound(db.create_project('Effects')['id'],'effects',{'prompt':'Rain','seconds':5})


def test_adapter_changes_require_a_new_sample(connected,monkeypatch):
    _,_,db=connected
    audio_engine.migrate()
    monkeypatch.setattr(audio_engine,'runtime_record',lambda _:{'manifest':'{"hash":"runtime"}'})
    monkeypatch.setattr(audio_engine,'fingerprint',lambda:'hardware')
    monkeypatch.setattr(audio_engine,'adapter_hash',lambda _:'new-adapter')
    from studio.model_library import pack
    db.execute('INSERT INTO audio_qualifications VALUES(?,?,?,?,?,?)',('voices-small',pack('voices-small')['revision'],'runtime','hardware',encode({'adapter_hash':'old-adapter'}),now()))
    assert audio_engine.qualification('voices-small') is None


def test_backup_restores_cast_script_and_history_under_new_ids(connected,tmp_path,monkeypatch):
    _,_,db=connected
    from studio import bundles,storage
    monkeypatch.setattr(bundles,'ROOT',tmp_path)
    monkeypatch.setattr(storage,'ROOT',tmp_path)
    for name in ['backups','projects','temp']:(tmp_path/name).mkdir()
    p=db.create_project('Script backup')
    cast=sound.add_cast(p['id'],'Mara','Vivian')
    line=sound.save_line(p['id'],{'text':'First version','cast_id':cast['id']})
    sound.save_line(p['id'],{'text':'Second version','cast_id':cast['id']},line['id'],1)
    result=bundles.create_bundle(p['id'])
    restored=bundles.restore_bundle(storage.role_folder('backups')/result['filename'])
    current=sound.view(restored['id'])
    assert current['cast'][0]['name']=='Mara' and current['cast'][0]['id']!=cast['id']
    assert current['lines'][0]['text']=='Second version'
    assert current['lines'][0]['cast_id']==current['cast'][0]['id']
    history=db.one('SELECT body FROM script_line_revisions WHERE id=?',(current['lines'][0]['id'],))
    assert json.loads(history['body'])['text']=='First version'
