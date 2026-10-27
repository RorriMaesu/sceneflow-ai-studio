import json
import os
import time

import pytest

from studio.store import Store, uid


@pytest.fixture
def care(tmp_path,monkeypatch):
    from studio import maintenance as m
    store=Store(tmp_path/'care.sqlite');monkeypatch.setattr(m,'ROOT',tmp_path);monkeypatch.setattr(m,'db',store)
    (tmp_path/'temp').mkdir();project=store.create_project('Care')
    def scratch(status='completed',age=90000,kind='export'):
        identifier=uid();store.execute('INSERT INTO jobs(id,project_id,kind,status,finished,snapshot,dependencies) VALUES(?,?,?,?,?,?,?)',(identifier,project['id'],kind,status,time.time()-age,'{}','[]'))
        path=tmp_path/'temp'/('export-'+identifier);path.mkdir();(path/'segment.mp4').write_bytes(b'owned scratch')
        os.utime(path,(time.time()-age,time.time()-age));return path
    return m,tmp_path,scratch,{'hash':'test-session'}


def test_quarantine_roundtrip_excludes_active_recent_and_foreign_files(care):
    m,root,scratch,session=care
    old=scratch();active=scratch('running');recent=scratch(age=60);foreign=root/'temp'/'personal';foreign.mkdir();(foreign/'keep.txt').write_text('keep')
    plan=m.review(session)
    assert [i['name'] for i in plan['items']]==[old.name]
    assert m.quarantine(plan['id'],session)['folders']==1 and not old.exists()
    assert active.exists() and recent.exists() and (foreign/'keep.txt').read_text()=='keep'
    assert m.history({'hash':'new-paired-session'})[0]['state']=='quarantined'
    assert m.restore(plan['id'],{'hash':'new-paired-session'})['folders']==1
    assert (old/'segment.mp4').read_bytes()==b'owned scratch'


def test_changed_plan_and_foreign_session_cannot_move_files(care):
    m,root,scratch,session=care;old=scratch();plan=m.review(session)
    with pytest.raises(ValueError,match='browser'):m.quarantine(plan['id'],{'hash':'other'})
    (old/'segment.mp4').write_bytes(b'changed')
    with pytest.raises(ValueError,match='changed'):m.quarantine(plan['id'],session)
    assert old.exists()


def test_restore_does_not_overwrite_new_scratch_and_recovers_interrupted_move(care):
    m,root,scratch,session=care;old=scratch();plan=m.review(session);m.quarantine(plan['id'],session)
    old.mkdir();(old/'new').write_text('keep')
    with pytest.raises(ValueError,match='overwritten'):m.restore(plan['id'],session)
    (old/'new').unlink();old.rmdir()
    record=m.read(plan['id'],session);record['state']='moving';record['items'][0]['moved']=False;m.save(record)
    assert m.restore(plan['id'],session)['folders']==1


def test_path_escape_and_link_rejected(care):
    m,root,scratch,session=care
    with pytest.raises(ValueError):m.safe_path(root,root.parent/'outside')
    with pytest.raises(ValueError):m.manifest_path('../../outside')
    old=scratch();target=root/'personal';target.mkdir()
    try:(old/'link').symlink_to(target,target_is_directory=True)
    except OSError:pytest.skip('Creating symlinks requires OS privilege on this Windows host.')
    os.utime(old,(time.time()-90000,time.time()-90000))
    with pytest.raises(ValueError,match='Linked'):m.review(session)


def test_desktop_notices_are_opt_in_and_never_contain_prompts(tmp_path,monkeypatch):
    from studio import desktop
    monkeypatch.setattr(desktop,'ROOT',tmp_path);monkeypatch.setattr(desktop,'settings',{'desktop_notifications':False});(tmp_path/'logs').mkdir()
    event={'status':'completed','kind':'video','snapshot':{'prompt':'private prompt'},'error':'private failure'}
    desktop.notice('job.updated',event);path=tmp_path/'logs'/'desktop-notice.json';assert not path.exists()
    desktop.settings['desktop_notifications']=True;desktop.notice('job.updated',event)
    assert json.loads(path.read_text())['message']=='Animation completed.'
    assert 'private' not in path.read_text()
