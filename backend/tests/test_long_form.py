import asyncio,json
import pytest
from .test_editing import editor,timeline,export
from .test_foundation import connected
from studio.store import encode,now,uid,Conflict


def test_unchanged_sections_reuse_cache_and_one_edit_renders_only_affected_sections(editor):
    store,m,p,scenes,assets,root=editor
    value=timeline(editor);first,_,job=export(editor)
    snap=json.loads(job['snapshot'])
    second=m['production'].queue_snapshot('export',snap,force=True)
    m['exports'].execute_export(second,snap)
    meta=json.loads(store.one("SELECT metadata FROM assets WHERE job_id=?",(second['id'],))['metadata'])
    assert meta['render_cache']['rendered']==0 and meta['render_cache']['reused']>=3
    clips=value['clips'];clips[0]['trim_out']=1
    m['exports'].save_timeline(p['id'],value['revision'],clips,[],value['settings'])
    changed,_,_=export(editor);details=json.loads(changed['metadata'])['render_cache']
    assert details['rendered']==2 and details['reused']==1 and details['max_inputs']<=8


def test_corrupt_cached_segment_is_rebuilt_instead_of_becoming_a_finished_video(editor):
    store,m,p,*_=editor
    timeline(editor);_,_,job=export(editor)
    cache=m['storage'].role_folder('cache')/'render-sections-v2'
    for path in cache.glob('*.mp4'):
        with path.open('ab') as out:out.write(b'corrupt')
    snap=json.loads(job['snapshot']);retry=m['production'].queue_snapshot('export',snap,force=True)
    m['exports'].execute_export(retry,snap)
    meta=json.loads(store.one('SELECT metadata FROM assets WHERE job_id=?',(retry['id'],))['metadata'])
    assert meta['render_cache']['invalid']>=3 and meta['frames']==48


def test_cancelled_export_stops_owned_work_and_keeps_source_media(editor):
    from studio.media import MediaCancelled
    store,m,p,scenes,assets,root=editor
    timeline(editor);job=m['exports'].queue_export(p['id'])
    store.execute('UPDATE jobs SET cancel_requested=1 WHERE id=?',(job['id'],))
    with pytest.raises(MediaCancelled):m['exports'].execute_export(job,json.loads(job['snapshot']))
    assert all(m['media'].asset_path(a['id']).is_file() for a in assets)
    assert not (m['storage'].export_folder(job['id'])/'worker.json').exists()


def test_master_uses_only_current_exports_from_its_actual_sequences(connected,monkeypatch):
    from studio import productions,master_export,music_planning
    client,headers,store=connected
    monkeypatch.setattr(master_export,'db',store)
    prod=client.post('/api/productions',json={'title':'A film','purpose':'movie'},headers=headers).json()
    client.post('/api/productions/'+prod['id']+'/episodes',json={'number':1,'title':'Opening'},headers=headers)
    value=productions.get(prod['id']);p=store.project(value['episodes'][0]['sequences'][0]['project_id'])
    assert not master_export.review(prod['id'])['episodes'][0]['ready']
    with pytest.raises(ValueError,match='current finished'):master_export.queue(prod['id'],value['revision'],[value['episodes'][0]['id']])
    asset=uid();store.execute('INSERT INTO assets(id,project_id,kind,path,sha256,metadata,created) VALUES(?,?,?,?,?,?,?)',(asset,p['id'],'export','fixture.mp4','a'*64,encode({'duration':3,'timeline_revision':p['timeline']['revision']}),now()))
    result=master_export.queue(prod['id'],value['revision'],[value['episodes'][0]['id']])
    frozen=json.loads(store.one('SELECT snapshot FROM jobs WHERE id=?',(result['job_id'],))['snapshot'])
    assert frozen['timeline']['clips'][0]['asset_id']==asset
    with pytest.raises(ValueError,match='this production'):master_export.queue(prod['id'],value['revision'],['another-episode'])
    music_planning.save_captions(p['id'],0,[{'start':0,'end':2,'text':'New captions'}],{'include_mp4':True})
    assert not master_export.review(prod['id'])['episodes'][0]['ready']


def test_dialogue_draft_is_append_only_reviewed_and_rejects_stale_scripts(connected,monkeypatch):
    from studio import script_planning as planner,script_audio
    _,_,store=connected;monkeypatch.setattr(planner,'db',store)
    p=store.create_project('Dialogue');planner.migrate()
    script_audio.save_line(p['id'],{'text':'Keep the opening.'})
    body={'characters':[{'name':'Mara','voice':'Vivian'}],'lines':[{'speaker':'Mara','text':'A new line.'}]}
    proposal=uid();store.execute('INSERT INTO script_proposals VALUES(?,?,?,?,?,?,?)',(proposal,p['id'],'job',planner.signature(p['id']),encode(body),'pending',now()))
    script_audio.save_line(p['id'],{'text':'I wrote something else.'})
    with pytest.raises(Conflict):asyncio.run(planner.apply(p['id'],proposal))
    store.execute('UPDATE script_proposals SET signature=? WHERE id=?',(planner.signature(p['id']),proposal))
    result=asyncio.run(planner.apply(p['id'],proposal))
    assert [l['text'] for l in result['lines']]==['Keep the opening.','I wrote something else.','A new line.']
    assert store.one('SELECT COUNT(*) n FROM jobs')['n']==0
    with pytest.raises(Conflict):asyncio.run(planner.apply(p['id'],proposal))
