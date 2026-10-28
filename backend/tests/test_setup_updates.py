import json,sqlite3,sys,zipfile
from pathlib import Path
import pytest
from .test_foundation import connected
from studio.store import encode,now,uid
from studio import tool_setup,model_library,runtime_installer,audio_engine
from update_package import digest,validate,extract,allowed
from apply_update import apply,main as recover


def test_complete_tool_setup_review_is_bound_to_its_browser(connected,monkeypatch):
    _,_,store=connected;tool_setup.migrate()
    value={'pack_id':'music','runtime_id':'music','runtime_hash':'recipe','models':[]}
    store.execute('INSERT INTO tool_setup_quotes VALUES(?,?,?,?)',('review','browser-one',encode(value),now()+100))
    with pytest.raises(ValueError,match='Review'):tool_setup.start('review',{'hash':'another-browser'},True)
    with pytest.raises(ValueError,match='Review'):tool_setup.start('review',{'hash':'browser-one'},False)
    assert store.one('SELECT COUNT(*) n FROM tool_setups')['n']==0


def test_setup_waits_for_verified_files_then_a_real_sample_before_ready(connected,monkeypatch):
    _,_,store=connected;tool_setup.migrate();p=store.create_project('Sample')
    store.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',('browser',None,'test',now()+3600,now()))
    store.execute('INSERT INTO model_downloads VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',('download','music','r','root','downloading','{}',0,1,None,now(),now(),0))
    plan={'pack_id':'music','models':[],'download_ids':['download'],'runtime_id':'music','runtime_hash':'recipe','program':None,'automatic_sample':True}
    store.execute('INSERT INTO tool_setups VALUES(?,?,?,?,?,?,?,?,?)',('setup','music','browser','queued','Review approved',encode(plan),None,now(),now()))
    monkeypatch.setattr(runtime_installer,'manifest',lambda _: {'hash':'recipe'})
    calls=[]
    def sample(_):
        calls.append('sample')
        store.execute('INSERT INTO jobs(id,project_id,kind,status,snapshot,dependencies,request_key,created) VALUES(?,?,?,?,?,?,?,?)',('sample',p['id'],'music','queued','{}','[]',uid(),now()))
        return {'job_id':'sample'}
    monkeypatch.setattr(audio_engine,'queue_probe',sample)
    row=lambda:store.one('SELECT * FROM tool_setups WHERE id=?',('setup',))
    tool_setup.advance(row());assert row()['status']=='downloading' and not calls
    store.execute("UPDATE model_downloads SET status='completed'")
    tool_setup.advance(row());assert row()['status']=='testing' and calls==['sample']
    tool_setup.advance(row());assert row()['status']=='testing' and len(calls)==1
    store.execute("UPDATE jobs SET status='completed' WHERE id='sample'")
    tool_setup.advance(row());assert row()['status']=='ready'


def test_paused_or_revoked_setup_does_not_start_another_step(connected,monkeypatch):
    _,_,store=connected;tool_setup.migrate()
    value={'runtime_id':'music','runtime_hash':'r','models':[],'download_ids':[],'automatic_sample':True}
    store.execute('INSERT INTO tool_setups VALUES(?,?,?,?,?,?,?,?,?)',('s','music','expired','queued','Queued',encode(value),None,now(),now()))
    tool_setup.advance(store.one('SELECT * FROM tool_setups'))
    assert store.one('SELECT status FROM tool_setups')['status']=='paused'
    monkeypatch.setattr(audio_engine,'queue_probe',lambda _:pytest.fail('Paused setup started a sample'))
    tool_setup.advance(store.one('SELECT * FROM tool_setups'))


def test_unavailable_voice_cloning_cannot_offer_a_useless_download(connected):
    with pytest.raises(ValueError,match='reference-recording'):model_library.quote_install('voices-character',{'hash':'browser'})


def release(folder,version='2.0.0'):
    files={'backend/run.py':b'print("new")','backend/studio/config.py':('VERSION = '+repr(version)).encode(),'backend/bootstrap-lock.txt':b'pin==1\n','frontend/dist/index.html':b'<main>New</main>','START_STUDIO.bat':b'new start','SETUP_STUDIO.bat':b'new setup'}
    for name,content in files.items():
        path=folder/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    manifest={'schema':1,'version':version,'files':[{'path':name,'bytes':len(content),'sha256':digest(folder/name)} for name,content in files.items()]}
    (folder/'release-manifest.json').write_text(json.dumps(manifest))
    return manifest


def installed(tmp_path):
    root=tmp_path/'installed';root.mkdir();(root/'local').mkdir();(root/'backend').mkdir();(root/'backend/bootstrap-lock.txt').write_bytes(b'pin==1\n');(root/'backend/run.py').write_text('old application')
    for name,content in [('config/settings.json','private choices'),('models/model.bin','private model'),('projects/script.txt','private story')]:
        path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
    stage=tmp_path/'stage';stage.mkdir();release(stage)
    plan={'id':uid(),'root':str(root.resolve()),'version':'2.0.0','stage':str(stage),'backup':str(tmp_path/'backup'),'manifest_sha256':digest(stage/'release-manifest.json'),'state':'prepared'}
    return root,stage,plan


def test_update_is_allowlisted_and_a_failed_start_restores_application_only(tmp_path):
    root,stage,plan=installed(tmp_path)
    def fail(*_):raise ValueError('Deliberate startup failure')
    with pytest.raises(ValueError,match='Deliberate'):apply(root,plan,probe=fail)
    assert plan['state']=='rolled_back' and (root/'backend/run.py').read_text()=='old application'
    assert not (root/'frontend/dist/index.html').exists()
    assert (root/'projects/script.txt').read_text()=='private story' and (root/'models/model.bin').read_text()=='private model'
    assert (root/'config/settings.json').read_text()=='private choices'


def test_successful_update_and_power_loss_recovery_preserve_current_data(tmp_path,monkeypatch):
    root,stage,plan=installed(tmp_path);apply(root,plan,probe=lambda *_:None)
    assert plan['state']=='applied' and (root/'backend/run.py').read_text()=='print("new")'
    plan['state']='checking';(root/'local/app-update.json').write_text(json.dumps(plan))
    monkeypatch.setattr(sys,'argv',['apply_update.py','--root',str(root),'--recover']);recover()
    assert (root/'backend/run.py').read_text()=='old application' and (root/'projects/script.txt').read_text()=='private story'
    assert json.loads((root/'local/app-update.json').read_text())['state']=='rolled_back'


def test_changed_dependencies_or_staged_files_do_not_replace_the_app(tmp_path):
    root,stage,plan=installed(tmp_path);(root/'backend/bootstrap-lock.txt').write_text('other pin')
    with pytest.raises(ValueError,match='dependencies'):apply(root,plan,probe=lambda *_:None)
    assert (root/'backend/run.py').read_text()=='old application'
    (stage/'backend/run.py').write_text('tampered')
    with pytest.raises(ValueError,match='checksum'):validate(stage)


@pytest.mark.parametrize('name',['../projects/story.txt','config/settings.json','models/model.bin','frontend/dist/../../config/token.json','C:/Windows/test','backend/studio/__pycache__/code.pyc'])
def test_update_archive_cannot_touch_private_or_external_paths(tmp_path,name):
    archive=tmp_path/'unsafe.zip'
    with zipfile.ZipFile(archive,'w') as out:out.writestr(name,b'unsafe')
    with pytest.raises(ValueError):extract(archive,tmp_path/'output')
    assert not allowed(name)
