import asyncio
import importlib
import json

import pytest
from PIL import Image,ImageDraw

from studio.store import Store,encode,now,uid


@pytest.fixture
def visual(tmp_path,monkeypatch):
    store=Store(tmp_path/'visual.sqlite');modules={n:importlib.import_module('studio.'+n) for n in ['continuity','production','adapters','media','quality','storage']}
    for module in modules.values():
        monkeypatch.setattr(module,'db',store)
        if hasattr(module,'ROOT'):monkeypatch.setattr(module,'ROOT',tmp_path)
    modules['production'].migrate()
    for original in modules['adapters'].BUILTINS:
        graph=modules['adapters'].qwen_graph(modules['adapters'].DUMMY,'test') if original['task']=='text_to_image' else modules['adapters'].wan_graph(modules['adapters'].DUMMY,'test','input.png')
        entry={**original,'graph':graph,'workflow_hash':modules['adapters'].graph_hash(graph),'status':'ready','reasons':[]}
        store.execute('INSERT INTO workflow_registry VALUES(?,?,?)',(entry['id'],encode(entry),now()))
    project=store.create_project('Continuity',settings={'width':64,'height':64});scene=store.add_scene(project['id'],'A',{'image_prompt':'A blue robot waving','video_prompt':'A slow wave'})
    source=tmp_path/'source.png';Image.new('RGB',(64,64),'blue').save(source)
    asset=modules['media'].add_asset(project['id'],scene['id'],None,'image',source)
    return store,modules,project,scene,asset,tmp_path


def test_reference_snapshot_owns_and_freezes_every_input(visual):
    store,m,p,s,a,path=visual
    p=store.update_project(p['id'],1,{'settings':{'reference_asset_ids':[a['id']],'visual_rules':'Keep the blue metal and one eye.'}})
    snapshot=m['production'].snapshot_for(s,p,'image')
    assert snapshot['workflow_id']=='qwen-image-21-reference'
    assert snapshot['reference_assets']==[{'id':a['id'],'sha256':a['sha256']}]
    assert m['production'].snapshot_is_current(snapshot,s,p,'image')
    job=m['production'].queue_snapshot('image',snapshot)
    changed=store.update_project(p['id'],p['revision'],{'settings':{'visual_rules':'Use red metal instead.'}})
    assert not m['production'].snapshot_is_current(snapshot,s,changed,'image')
    assert json.loads(store.one('SELECT snapshot FROM jobs WHERE id=?',(job['id'],))['snapshot'])['reference_assets']==snapshot['reference_assets']
    other=store.create_project('Other')
    with pytest.raises(ValueError,match='owned by this project'):m['continuity'].owned_references(store,other['id'],[a['id']])


def test_qwen_reference_graph_has_flattened_refs_and_real_latent():
    from studio.adapters import DUMMY,qwen_reference_graph
    graph=qwen_reference_graph(DUMMY,'test',['first.png','second.png'],'mask.png')
    assert graph['text']['inputs']['images.image_1']==['reference_1_scale',0]
    assert 'images' not in graph['text']['inputs']
    assert graph['text']['inputs']['resolution']==0
    assert graph['sample']['inputs']['latent_image']==['edit_noise_mask',0]
    assert qwen_reference_graph(DUMMY,'test',['first.png'])['sample']['inputs']['latent_image']==['text',2]
    assert graph['mask']['inputs']['channel']=='red'
    assert graph['save']['inputs']['images']==['composite',0]


def test_masked_output_rejects_any_change_outside_painted_pixels(visual):
    store,m,p,s,a,path=visual
    mask=path/'mask.png';image=Image.new('RGB',(64,64),'black');ImageDraw.Draw(image).rectangle((20,20,40,40),fill='white');image.save(mask)
    ma=m['media'].add_asset(p['id'],None,None,'image',mask,extra={'role':'edit_mask','mask_for':a['id']})
    snapshot={'project_id':p['id'],'scene_id':s['id'],'width':64,'height':64,'source_asset_id':a['id'],'source_sha256':a['sha256'],'mask_asset_id':ma['id'],'mask_sha256':ma['sha256']}
    job=m['production'].queue_snapshot('image',snapshot)
    corrected=path/'corrected.png';image=Image.new('RGB',(64,64),'blue');ImageDraw.Draw(image).rectangle((22,22,38,38),fill='red');image.save(corrected)
    output=m['media'].add_asset(p['id'],s['id'],job['id'],'image',corrected,a['id'])
    assert json.loads(output['metadata'])['outside_mask_unchanged']
    image.putpixel((0,0),(255,0,0));image.save(corrected)
    with pytest.raises(ValueError,match='outside the painted area'):m['media'].add_asset(p['id'],s['id'],job['id'],'image',corrected,a['id'])
    with pytest.raises(ValueError,match='Select a scene|cannot be selected'):m['media'].select_asset(ma['id'])


def test_export_history_is_project_scoped_and_does_not_hide_old_movies(visual):
    store,m,p,s,a,path=visual
    other=store.create_project('Many newer assets')
    with store.connect(True) as con:
        con.executemany('INSERT INTO assets(id,project_id,kind,metadata,created) VALUES(?,?,?,?,?)',[(uid(),other['id'],'image','{}',index+1000) for index in range(125)])
    ids=[]
    for index in range(25):
        identifier=uid();ids.append(identifier);store.execute('INSERT INTO assets(id,project_id,kind,metadata,created) VALUES(?,?,?,?,?)',(identifier,p['id'],'export','{}',index))
    first=asyncio.run(m['continuity'].project_exports(p['id'],1));second=asyncio.run(m['continuity'].project_exports(p['id'],2))
    assert first['total']==25 and first['has_more'] and len(first['items'])==20
    assert not second['has_more'] and len(second['items'])==5
    assert {a['id'] for a in first['items']+second['items']}==set(ids)


def test_zero_quality_retry_budget_means_zero(visual):
    store,m,p,s,a,path=visual
    job=m['production'].queue_snapshot('image',{'project_id':p['id'],'scene_id':s['id'],'scene_revision_id':s['revision_id']})
    assert not m['quality'].retry_allowed(store,job,{'qa_policy':{'qa_regenerate':True,'max_retries':0}},.2)


def test_ending_frame_is_frozen_and_changes_only_video_inputs(visual):
    store,m,p,s,a,path=visual
    m['media'].select_asset(a['id'],True);s=store.scene(s['id'])
    image_before=m['production'].stage_signature(s,p,'image');video_before=m['production'].snapshot_for(s,p,'video',a)
    changed=store.update_scene(s['id'],s['revision'],body={'ending_asset_id':a['id']})
    assert m['production'].stage_signature(changed,p,'image')==image_before
    assert not m['production'].snapshot_is_current(video_before,changed,p,'video')
    snapshot=m['production'].snapshot_for(changed,p,'video',a)
    assert snapshot['workflow_id']=='wan22-first-last' and snapshot['ending_asset_id']==a['id'] and snapshot['ending_sha256']==a['sha256']
    graph,_=m['adapters'].registry.build(snapshot['workflow_id'],snapshot,'test','start.png',ending='end.png')
    assert graph['condition']['class_type']=='WanFirstLastFrameToVideo' and graph['ending']['inputs']['image']=='end.png'
    other=store.create_project('Other project');foreign=m['media'].add_asset(other['id'],None,None,'image',path/'source.png')
    changed=store.update_scene(s['id'],changed['revision'],body={'ending_asset_id':foreign['id']})
    with pytest.raises(ValueError,match='owned by this project'):m['production'].snapshot_for(changed,p,'video',a)


def test_correction_rejects_transparency_before_queueing(visual):
    store,m,p,s,a,path=visual
    transparent=path/'transparent.png';Image.new('RGBA',(64,64),(0,0,255,100)).save(transparent)
    asset=m['media'].add_asset(p['id'],s['id'],None,'image',transparent)
    with pytest.raises(ValueError,match='opaque'):
        asyncio.run(m['continuity'].correct(asset['id'],m['continuity'].Correction(prompt='Make the body red')))
    assert not store.jobs()
