import hashlib,json,wave
from pathlib import Path
import pytest
from .test_foundation import connected
from .test_editing import editor
from studio import music_planning as edit,caption_engine,media
from studio.store import Conflict,encode,now,uid

@pytest.fixture
def recording(connected,tmp_path,monkeypatch):
    _,_,db=connected
    monkeypatch.setattr(media,'ROOT',tmp_path)
    p=db.create_project('Music video')
    path=tmp_path/'projects'/p['id']/'song.wav';path.parent.mkdir(parents=True)
    with wave.open(str(path),'wb') as out:out.setnchannels(1);out.setsampwidth(2);out.setframerate(16000);out.writeframes(b'\0\0'*160000)
    asset_id=uid();digest=hashlib.sha256(path.read_bytes()).hexdigest()
    db.execute('INSERT INTO assets(id,project_id,kind,path,sha256,metadata,created) VALUES(?,?,?,?,?,?,?)',(asset_id,p['id'],'audio',str(path.relative_to(tmp_path)),digest,encode({'duration':10.,'audio_streams':1,'role':'music'}),now()))
    return db,p,asset_id,path

def test_song_is_locked_by_hash_and_replacement_requires_review(recording):
    db,p,asset,path=recording
    current=edit.lock_song(p['id'],asset)
    assert current['master']['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError,match='replacement'):edit.lock_song(p['id'],asset,1)
    with pytest.raises(Conflict):edit.lock_song(p['id'],asset,0,True)
    assert edit.lock_song(p['id'],asset,1,True)['master']['revision']==2

def test_song_sections_cannot_overlap_or_escape_the_locked_song(recording):
    _,p,asset,_=recording
    current=edit.lock_song(p['id'],asset)
    good=[{'id':'verse','label':'Verse','start':0.,'end':4.},{'id':'chorus','label':'Chorus','start':4.,'end':10.}]
    saved=edit.save_sections(p['id'],current['sections']['revision'],good)
    assert saved['sections']['items']==good
    with pytest.raises(ValueError):edit.save_sections(p['id'],saved['sections']['revision'],[{**good[0],'end':11.}])
    with pytest.raises(ValueError):edit.save_sections(p['id'],saved['sections']['revision'],[good[0],{**good[1],'start':3.}])
    assert edit.song(p['id'])['master']['asset_id']==asset

def test_changed_song_file_is_detected_before_placement(recording):
    _,p,asset,path=recording
    edit.lock_song(p['id'],asset)
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='changed'):edit.verified_master(p['id'])

def test_caption_revisions_and_subtitle_clock_are_preserved(connected):
    _,_,db=connected;p=db.create_project('Captions')
    original=edit.save_captions(p['id'],0,[{'start':1.125,'end':3.4,'text':'Welcome.'}])
    edit.save_captions(p['id'],1,[{'start':1.2,'end':3.5,'text':'Welcome back.'}])
    with pytest.raises(Conflict):edit.save_captions(p['id'],1,[])
    assert json.loads(db.one('SELECT body FROM caption_revisions')['body'])==original['items']
    assert '00:00:01,125 --> 00:00:03,400' in edit.subtitle_text(original['items'])
    assert edit.stamp(3600.001,True)=='01:00:00.001'

@pytest.mark.parametrize('items',[[{'start':0,'end':float('nan'),'text':'Bad'}],[{'start':4,'end':3,'text':'Bad'}],[{'start':0,'end':1,'text':''}]])
def test_invalid_caption_times_or_text_are_rejected(items):
    with pytest.raises(ValueError):edit.validate_captions(items)

def test_caption_source_must_belong_to_the_current_sequence(recording):
    db,p,asset,_=recording
    other=db.create_project('Other')
    with pytest.raises(ValueError,match='this sequence'):caption_engine.queue(other['id'],{'asset_id':asset,'test':True})

def test_recognized_draft_cannot_overwrite_a_later_caption_edit(connected):
    import asyncio
    _,_,db=connected;p=db.create_project('Review');edit.migrate()
    db.execute('INSERT INTO caption_proposals VALUES(?,?,?,?,?,?,?,?)',('proposal',p['id'],'job',0,encode([{'start':0,'end':2,'text':'Suggested'}]),'{}','pending',now()))
    edit.save_captions(p['id'],0,[{'start':0,'end':2,'text':'My saved words'}])
    with pytest.raises(Conflict):asyncio.run(caption_engine.apply(p['id'],'proposal'))
    assert edit.captions(p['id'])['items'][0]['text']=='My saved words'

def test_song_markers_captions_and_history_survive_a_portable_backup(recording,tmp_path,monkeypatch):
    import shutil
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('Media verification needs FFmpeg/FFprobe')
    from studio import bundles,storage
    db,p,asset,path=recording
    monkeypatch.setattr(bundles,'ROOT',tmp_path);monkeypatch.setattr(storage,'ROOT',tmp_path)
    for name in ['backups','temp']:(tmp_path/name).mkdir(exist_ok=True)
    edit.lock_song(p['id'],asset)
    edit.save_sections(p['id'],1,[{'id':'part','label':'Intro','start':0.,'end':10.}])
    edit.save_captions(p['id'],0,[{'start':1.,'end':3.,'text':'First'}])
    edit.save_captions(p['id'],1,[{'start':1.,'end':3.,'text':'Corrected'}])
    bundle=bundles.create_bundle(p['id']);restored=bundles.restore_bundle(storage.role_folder('backups')/bundle['filename'])
    saved=edit.song(restored['id'])
    assert saved['master']['asset_id']!=asset and saved['master']['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert saved['sections']['items'][0]['label']=='Intro'
    assert edit.captions(restored['id'])['items'][0]['text']=='Corrected'
    assert json.loads(db.one('SELECT body FROM caption_revisions WHERE project_id=?',(restored['id'],))['body'])[0]['text']=='First'

def test_subtitle_import_preserves_real_times_and_rejects_invalid_clocks():
    items=edit.parse_subtitles('1\n00:00:01,125 --> 00:00:03,400\nHello.\n')
    assert items==[{'start':1.125,'end':3.4,'text':'Hello.'}]
    assert edit.parse_subtitles('WEBVTT\n\n00:01.125 --> 00:03.400\nHello.\n')==items
    with pytest.raises(ValueError):edit.parse_subtitles('1\n00:65:00,000 --> 01:00:00,000\nWrong clock')

def test_saved_caption_track_is_really_present_in_the_finished_mp4(editor,monkeypatch):
    db,modules,p,scenes,assets,root=editor
    monkeypatch.setattr(edit,'db',db)
    timeline=modules['exports'].save_timeline(p['id'],p['timeline']['revision'],[{'id':'clip','scene_id':scenes[0]['id'],'asset_id':assets[0]['id'],'trim_in':0,'trim_out':2,'speed':1}],[],{'width':320,'height':180,'fps':12,'audio_mode':'preserve'})
    edit.save_captions(p['id'],0,[{'start':.25,'end':1.75,'text':'Caption proof'}],{'kind':'manual','include_mp4':True})
    job=modules['exports'].queue_export(p['id'])
    modules['exports'].execute_export(job,json.loads(job['snapshot']))
    result=db.one("SELECT metadata FROM assets WHERE job_id=? AND kind='export'",(job['id'],))
    metadata=json.loads(result['metadata'])
    assert metadata['subtitle_streams']==1 and metadata['audio_streams']==1 and metadata['frames']==24


def test_fitting_visuals_keeps_song_speed_exact_and_reuses_one_music_track(editor,monkeypatch):
    db,modules,p,scenes,assets,root=editor
    monkeypatch.setattr(edit,'db',db)
    audio_path=root/'temp'/'song.wav'
    modules['media'].run_tool([modules['media'].executable('ffmpeg'),'-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=3',str(audio_path)])
    audio=modules['media'].add_asset(p['id'],None,None,'audio',audio_path,extra={'role':'music'})
    edit.lock_song(p['id'],audio['id'])
    clips=[{'id':str(i),'scene_id':scenes[i]['id'],'asset_id':assets[i]['id'],'trim_in':0,'trim_out':2,'speed':1,'transition':'fade'} for i in range(3)]
    modules['exports'].save_timeline(p['id'],p['timeline']['revision'],clips,[],{'width':320,'height':180,'fps':12,'audio_mode':'mixed','transition':'fade','repeats':2})
    fitted=edit.place_song(p['id'],0,3,True)
    assert len(fitted['clips'])==2 and fitted['clips'][-1]['trim_out']==1
    assert all(c['transition']=='cut' and c['speed']==1 for c in fitted['clips'])
    assert fitted['settings']['repeats']==1 and len(fitted['audio'])==1
    assert edit.place_song(p['id'],0,3,True)['audio'][0]['trim_out']==3
    assert len(db.project(p['id'])['timeline']['audio'])==1
    current=db.project(p['id'])['timeline']
    modules['exports'].save_timeline(p['id'],current['revision'],current['clips'][:1],current['audio'],current['settings'])
    with pytest.raises(ValueError,match='more seconds'):edit.place_song(p['id'],0,3,True)
