import importlib
import json
import shutil
import zipfile

import pytest
from PIL import Image

from studio.store import Conflict,Store,encode,uid


@pytest.fixture
def editor(tmp_path,monkeypatch):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg and FFprobe are needed for media integration tests')
    store=Store(tmp_path/'editing.sqlite')
    modules={n:importlib.import_module('studio.'+n) for n in ['exports','editing_export','media','production','bundles']}
    for module in modules.values():
        monkeypatch.setattr(module,'db',store)
        if hasattr(module,'ROOT'):monkeypatch.setattr(module,'ROOT',tmp_path)
    for name in ['temp','projects','backups']:(tmp_path/name).mkdir()
    monkeypatch.setitem(modules['media'].settings,'ffmpeg',shutil.which('ffmpeg'))
    monkeypatch.setitem(modules['media'].settings,'ffprobe',shutil.which('ffprobe'))
    modules['production'].migrate()
    p=store.create_project('Labeled fixture');scenes=[];assets=[]
    for color,freq in [('red',500),('green',1000),('blue',1500)]:
        s=store.add_scene(p['id'],color);scenes.append(s);path=tmp_path/'temp'/(color+'.mp4')
        modules['media'].run_tool([shutil.which('ffmpeg'),'-y','-v','error','-f','lavfi','-i',f'color=c={color}:s=320x180:r=12:d=2','-f','lavfi','-i',f'sine=frequency={freq}:sample_rate=48000:duration=2','-shortest','-c:v','libx264','-threads','1','-pix_fmt','yuv420p','-c:a','aac',str(path)])
        a=modules['media'].add_asset(p['id'],s['id'],None,'video',path);assets.append(a)
    return store,modules,store.project(p['id']),scenes,assets,tmp_path


def timeline(editor,transition='cut',audio_mode='preserve',loop='none',repeats=1):
    store,m,p,scenes,assets,_=editor
    order=[2,0]
    clips=[{'id':uid(),'asset_id':assets[i]['id'],'scene_id':scenes[i]['id'],'trim_in':0,'trim_out':2,'speed':1,'volume':1,'transition':'inherit'} for i in order]
    settings={'width':320,'height':180,'fps':12,'codec':'h264','crf':18,'fit':'pad','audio_mode':audio_mode,'transition':transition,'transition_duration':.25,'loop':loop,'repeats':repeats}
    return m['exports'].save_timeline(p['id'],p['timeline']['revision'],clips,[],settings)


def export(editor):
    store,m,p,*_=editor
    job=m['exports'].queue_export(p['id'])
    m['exports'].execute_export(job,json.loads(job['snapshot']))
    asset=store.one("SELECT * FROM assets WHERE job_id=? AND kind='export'",(job['id'],))
    return asset,m['media'].asset_path(asset['id']),job


def test_export_order_audio_and_frozen_snapshot(editor):
    store,m,p,scenes,assets,root=editor
    value=timeline(editor)
    job=m['exports'].queue_export(p['id']);snapshot=json.loads(job['snapshot'])
    m['exports'].save_timeline(p['id'],value['revision'],list(reversed(value['clips'])),[],value['settings'])
    m['exports'].execute_export(job,snapshot)
    asset=store.one("SELECT * FROM assets WHERE job_id=? AND kind='export'",(job['id'],));path=m['media'].asset_path(asset['id']);info=m['media'].probe(path)
    assert info['audio_streams']==1 and info['audio'][0]['channels']==2 and info['audio'][0]['sample_rate']=='48000'
    assert abs(info['duration']-4)<.2
    for at,expected in [(.2,2),(2.5,0)]:
        frame=root/'temp'/f'frame{at}.png'
        m['media'].run_tool([shutil.which('ffmpeg'),'-y','-v','error','-ss',str(at),'-i',str(path),'-frames:v','1',str(frame)])
        with Image.open(frame) as image:
            rgb=image.convert('RGB').getpixel((160,90));assert rgb[expected]>180 and min(rgb)<40
    m['exports'].execute_export(job,snapshot)
    assert store.one("SELECT COUNT(*) n FROM assets WHERE job_id=?",(job['id'],))['n']==1


@pytest.mark.parametrize('transition,loop,repeats',[('fade','none',1),('fade_black','fade_black',2),('dissolve','crossfade',2)])
def test_transitions_loops_and_silent_exports_decode(editor,transition,loop,repeats):
    timeline(editor,transition,'silent',loop,repeats)
    asset,path,_=export(editor);meta=json.loads(asset['metadata'])
    assert meta['audio_streams']==0 and abs(meta['duration']-meta['expected_duration'])<.25


def test_imported_audio_mix_trim_fades_and_ducking(editor):
    store,m,p,scenes,assets,root=editor
    value=timeline(editor,audio_mode='mixed')
    audio_path=root/'temp'/'tone.wav';m['media'].run_tool([shutil.which('ffmpeg'),'-y','-v','error','-f','lavfi','-i','sine=frequency=440:duration=3',str(audio_path)])
    audio=m['media'].add_asset(p['id'],None,None,'audio',audio_path)
    tracks=[{'id':uid(),'asset_id':audio['id'],'role':'music','trim_in':0,'trim_out':3,'start':0,'volume':.5,'fade_in':.1,'fade_out':.1,'duck':True},{'id':uid(),'asset_id':audio['id'],'role':'voiceover','trim_in':0,'trim_out':1,'start':1,'volume':.4}]
    m['exports'].save_timeline(p['id'],value['revision'],value['clips'],tracks,value['settings'])
    asset,path,_=export(editor)
    assert m['media'].probe(path)['audio_streams']==1


def test_changed_source_hash_blocks_frozen_export(editor):
    store,m,p,scenes,assets,_=editor;timeline(editor)
    job=m['exports'].queue_export(p['id']);path=m['media'].asset_path(assets[2]['id'])
    with path.open('ab') as file:file.write(b'changed')
    with pytest.raises(ValueError,match='changed on disk'):m['exports'].execute_export(job,json.loads(job['snapshot']))


def test_backup_restore_uses_new_ids_and_never_resumes_work(editor):
    store,m,p,scenes,assets,root=editor;timeline(editor)
    m['media'].select_asset(assets[0]['id'],True)
    bundle=m['bundles'].create_bundle(p['id']);restored=m['bundles'].restore_bundle(root/'backups'/bundle['filename'])
    assert restored['id']!=p['id'] and restored['mode']=='hybrid'
    assert len(restored['scenes'])==3
    assert set(s['id'] for s in restored['scenes']).isdisjoint(s['id'] for s in scenes)
    for scene in restored['scenes']:
        for asset in scene['assets']:
            assert m['media'].asset_path(asset['id']).is_file()
    assert m['production'].state(restored['id'])['paused']==1
    assert store.project(p['id'])['title']==p['title']


def test_bundle_path_escape_rejected_before_writing(editor):
    store,m,p,scenes,assets,root=editor
    attack=root/'temp'/'attack.zip'
    with zipfile.ZipFile(attack,'w') as archive:
        archive.writestr('../escape.txt','bad');archive.writestr('manifest.json','{}')
    with pytest.raises(ValueError,match='Unsafe'):m['bundles'].restore_bundle(attack)
    assert not (root/'escape.txt').exists()
