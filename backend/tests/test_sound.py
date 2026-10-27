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
