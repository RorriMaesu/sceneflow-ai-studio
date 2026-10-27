import asyncio
import pytest
from .test_foundation import connected
from studio import productions as library
from studio.store import Conflict,encode,now

@pytest.fixture
def collection(connected,monkeypatch):
    _,_,db=connected
    monkeypatch.setattr(library,'db',db)
    p=asyncio.run(library.create(library.NewProduction(title='A whole show',purpose='series',brief='Two friends explore a new world.')))
    return db,p

def test_show_outline_creates_empty_sequences_without_footage(collection):
    db,p=collection
    plan={'episodes':[{'title':'Pilot','summary':'The first discovery','start_state':'Strangers','end_state':'Friends'},{'title':'Return','summary':'A second discovery','start_state':'Friends','end_state':'Partners'}]}
    db.execute('INSERT INTO production_outlines VALUES(?,?,?,?,?,?,?,?)',('proposal',p['id'],'job',p['revision'],1,encode(plan),'pending',now()))
    result=asyncio.run(library.apply(p['id'],'proposal'))
    assert len(result['episodes'])==2
    assert db.all('SELECT id FROM jobs')==[] and db.all('SELECT id FROM assets')==[]
    assert len(db.projects())==2
    assert all(len(e['sequences'])==1 for e in result['episodes'])
    assert all(not db.project(e['sequences'][0]['project_id'])['scenes'] for e in result['episodes'])

def test_stale_outline_cannot_overwrite_new_shared_guide(collection):
    db,p=collection
    plan={'episodes':[{'title':'Pilot','summary':'A discovery','start_state':'Before','end_state':'After'}]}
    db.execute('INSERT INTO production_outlines VALUES(?,?,?,?,?,?,?,?)',('proposal',p['id'],'job',p['revision'],1,encode(plan),'pending',now()))
    asyncio.run(library.canon(p['id'],library.Canon(revision=1,canon='The new guide')))
    with pytest.raises(Conflict):asyncio.run(library.apply(p['id'],'proposal'))
    assert library.get(p['id'])['episodes']==[]

def test_sequence_and_cast_scope_are_bound_to_real_membership(collection):
    db,p=collection
    result=asyncio.run(library.episode(p['id'],library.Episode(number=1,title='Pilot')))
    episode=result['episodes'][0];project=episode['sequences'][0]['project_id']
    assert library.cast_scope(project)==p['root_project_id']
    standalone=db.create_project('Legacy')
    assert library.cast_scope(standalone['id'])==standalone['id']
    other=asyncio.run(library.create(library.NewProduction(title='Other',purpose='movie')))
    with pytest.raises(ValueError):asyncio.run(library.sequence(other['id'],episode['id'],library.Sequence(title='Wrong')))

def test_duplicate_episode_numbers_do_not_add_orphan_projects(collection):
    db,p=collection
    asyncio.run(library.episode(p['id'],library.Episode(number=1,title='Pilot')))
    count=len(db.projects())
    with pytest.raises(ValueError):asyncio.run(library.episode(p['id'],library.Episode(number=1,title='Duplicate')))
    assert len(db.projects())==count

def test_episodes_share_cast_without_sharing_their_script_lines(collection):
    db,p=collection
    from studio import script_audio
    asyncio.run(library.episode(p['id'],library.Episode(number=1,title='Pilot')))
    result=asyncio.run(library.episode(p['id'],library.Episode(number=2,title='Return')))
    first,second=[e['sequences'][0]['project_id'] for e in result['episodes']]
    cast=script_audio.add_cast(first,'Mara','Vivian')
    script_audio.save_line(second,{'text':'Welcome back','cast_id':cast['id']})
    assert script_audio.view(first)['cast'][0]['id']==script_audio.view(second)['cast'][0]['id']
    assert not script_audio.view(first)['lines'] and len(script_audio.view(second)['lines'])==1
    standalone=db.create_project('Other show')
    with pytest.raises(ValueError):script_audio.save_line(standalone['id'],{'text':'Wrong cast','cast_id':cast['id']})

def test_episode_edits_are_revision_checked_and_preserve_sequence_work(collection):
    db,p=collection
    result=asyncio.run(library.episode(p['id'],library.Episode(number=1,title='Pilot')))
    e=result['episodes'][0];project_id=e['sequences'][0]['project_id']
    scene=db.add_scene(project_id,'Opening',{'summary':'Saved work'})
    values=library.EpisodeEdit(revision=1,title='Revised pilot',summary='New summary',start_state='Alone',end_state='Friends')
    changed=asyncio.run(library.edit_episode(p['id'],e['id'],values))
    assert changed['revision']==2 and db.scene(scene['id'])['body']['summary']=='Saved work'
    with pytest.raises(Conflict):asyncio.run(library.edit_episode(p['id'],e['id'],values))
