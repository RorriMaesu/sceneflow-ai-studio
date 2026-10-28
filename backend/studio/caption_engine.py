"""Caption jobs produce reviewable drafts. Audio, songs and existing captions stay intact."""
import asyncio,ast,hashlib,json,re,difflib
from pathlib import Path
from fastapi import APIRouter,Depends
from pydantic import BaseModel,ConfigDict,Field
from . import model_library,provider_workers,runtime_installer,music_planning
from .audio_engine import fingerprint,files_unchanged
from .store import db,encode,now,uid,Conflict
from .media import asset_path,executable
from .security import require_session

router=APIRouter(prefix='/api')
GIB=1024**3
ALIGN_LANGUAGES=['English','Chinese','Cantonese','French','German','Italian','Portuguese','Russian','Spanish']

def migrate():
    music_planning.migrate(db);provider_workers.migrate(db)
    with db.connect(True) as con:con.execute('CREATE TABLE IF NOT EXISTS caption_qualifications(pack_id TEXT,recipe TEXT,hardware TEXT,body TEXT,created REAL,PRIMARY KEY(pack_id,recipe,hardware))')

def runtime():
    migrate()
    row=db.one("SELECT * FROM provider_runtimes WHERE id='captions' AND state='ready'")
    if not row or json.loads(row['manifest']).get('hash')!=runtime_installer.manifest('captions')['hash']:return None
    try:provider_workers.runtime_python('captions')
    except ValueError:return None
    return row

def adapter_hash():
    tree=ast.parse((Path(__file__).resolve().parents[1]/'caption_worker.py').read_text(encoding='utf-8'))
    return hashlib.sha256(ast.dump(tree,include_attributes=False).encode()).hexdigest()

def recipe(pack_id):
    return hashlib.sha256(encode({'pack':model_library.pack(pack_id)['revision'],'runtime':runtime_installer.manifest('captions')['hash'],'adapter':adapter_hash()}).encode()).hexdigest()

def qualification(pack_id):
    if not runtime():return None
    row=db.one('SELECT * FROM caption_qualifications WHERE pack_id=? AND recipe=? AND hardware=?',(pack_id,recipe(pack_id),fingerprint()))
    return json.loads(row['body']) if row else None

def installed(pack_id):
    model_library.migrate();value=model_library.pack(pack_id)
    row=db.one('SELECT * FROM model_installs WHERE pack_id=? AND revision=? ORDER BY verified DESC',(pack_id,value['revision']))
    if not row:raise ValueError('Download the caption or word-timing model in Setup first.')
    return value,row,model_library.install_path(value,row['root_id'])

def queue(project_id,body):
    from .production import queue_snapshot
    migrate();db.project(project_id)
    asset=db.one("SELECT * FROM assets WHERE id=? AND project_id=? AND kind IN ('audio','video','export')",(body['asset_id'],project_id))
    if not asset:raise ValueError('Choose a recording from this sequence.')
    metadata=json.loads(asset['metadata']);is_music=metadata.get('role')=='music'
    master=music_planning.song(project_id)['master']
    if master and (asset['id']==master['asset_id'] or metadata.get('song_master_source_id')==master['asset_id']):is_music=True
    if metadata.get('audio_streams')!=1:raise ValueError('Choose a recording or video with one sound track. Import a single-track audio mix for multi-track sources.')
    mode=body.get('mode','transcribe');timing=bool(body.get('word_timing',True)) and not is_music
    if mode=='align':
        if is_music:raise ValueError('Singing word alignment is not qualified. Recognize lyrics, then adjust their timing manually.')
        if not body.get('text','').strip():raise ValueError('Enter the spoken words you want to align.')
        timing=True
        if body.get('language','English') not in ALIGN_LANGUAGES:raise ValueError('Choose a supported spoken-word timing language.')
    track=None
    if body.get('track_id'):
        track=next((t for t in db.project(project_id)['timeline'].get('audio',[]) if t['id']==body['track_id'] and t['asset_id']==asset['id']),None)
        if not track:raise ValueError('Choose an audio track in the saved edit.')
    start=float(track.get('trim_in',0)) if track else 0.
    end=float(track['trim_out']) if track else metadata['duration'];seconds=end-start
    offset=float(track.get('start',0)) if track else 0.
    if not .1<seconds<=1800 or mode=='align' and seconds>60:raise ValueError('Use recognition recordings up to 30 minutes, or known-speech alignment clips up to one minute. Trim a track or split longer audio.')
    if body.get('test') and seconds>30:
        if mode=='align':raise ValueError('Choose known speech up to 30 seconds for the first alignment test.')
        seconds=30
    if offset+seconds>36000:raise ValueError('Move the recording earlier in the saved edit before creating captions.')
    packs=(['captions'] if mode=='transcribe' else [])+(['alignment'] if timing else [])
    rt=runtime()
    if not rt:raise ValueError('Finish the caption program setup in Setup & downloads.')
    frozen=[]
    for pack_id in packs:
        value,row,folder=installed(pack_id)
        if not body.get('test') and not qualification(pack_id):raise ValueError('Run the short caption test on a recording before using this tool for a longer production.')
        frozen.append({'pack_id':pack_id,'revision':value['revision'],'root_id':row['root_id'],'path':str(folder),'recipe':recipe(pack_id)})
    expected=None
    if asset['job_id']:
        original=db.one("SELECT snapshot FROM jobs WHERE id=? AND kind='speech'",(asset['job_id'],))
        if original:expected=json.loads(original['snapshot']).get('inputs',{}).get('text')
    snapshot={'project_id':project_id,'scene_id':None,'title':'Caption draft','source_asset_id':asset['id'],'source_sha256':asset['sha256'],'source_start':start,'seconds':seconds,'offset':offset,
              'mode':mode,'word_timing':timing,'is_music':is_music,'language':body.get('language') or None,'text':body.get('text',''),'test':bool(body.get('test')),
              'packs':frozen,'runtime_hash':json.loads(rt['manifest'])['hash'],'hardware':fingerprint(),'adapter_hash':adapter_hash(),'caption_revision':music_planning.captions(project_id)['revision'],
              'expected_text':expected if not track else None,'manual_override':True,'manual_requested_at':now(),'resource_profile':{'gpu_free':6*GIB,'ram_free':6*GIB,'basis':'Batch-one, bounded native caption chunks; recognition and word timing unload between stages.'}}
    return {'job_id':queue_snapshot('transcribe' if mode=='transcribe' else 'align',snapshot)['id']}

async def execute(job,snapshot):
    from .production import update_job
    migrate()
    rt=runtime()
    if not rt or json.loads(rt['manifest'])['hash']!=snapshot['runtime_hash'] or snapshot['hardware']!=fingerprint() or snapshot['adapter_hash']!=adapter_hash():raise ValueError('The caption tool changed. Run its short test again before retrying.')
    update_job(job['id'],'running',started=now(),progress=.01,error=None)
    asset=db.one("SELECT * FROM assets WHERE id=? AND project_id=? AND kind IN ('audio','video','export')",(snapshot['source_asset_id'],job['project_id']))
    if not asset or asset['sha256']!=snapshot['source_sha256']:raise ValueError('The selected recording changed or no longer belongs to this sequence.')
    source=asset_path(asset['id'])
    def check_source():
        with source.open('rb') as handle:
            if hashlib.file_digest(handle,'sha256').hexdigest()!=snapshot['source_sha256']:raise ValueError('The recording changed on disk. Reimport it before making captions.')
    await asyncio.to_thread(check_source)
    inputs={k:snapshot[k] for k in ['mode','word_timing','is_music','language','text','source_start','seconds']}
    inputs.update(source_path=str(source),ffmpeg=executable('ffmpeg'))
    for pack in snapshot['packs']:
        value,row,folder=installed(pack['pack_id'])
        if value['revision']!=pack['revision'] or row['root_id']!=pack['root_id'] or recipe(pack['pack_id'])!=pack['recipe']:raise ValueError('A caption model changed. Run a fresh test before retrying.')
        await asyncio.to_thread(files_unchanged,value,row)
        inputs['asr_path' if pack['pack_id']=='captions' else 'aligner_path']=str(folder)
    if db.one('SELECT cancel_requested FROM jobs WHERE id=?',(job['id'],))['cancel_requested']:
        update_job(job['id'],'cancelled',finished=now());return
    try:result,folder=await provider_workers.run(job,'captions',inputs,timeout=1800)
    except provider_workers.CreationCancelled:
        update_job(job['id'],'cancelled',finished=now(),error='Stopped caption creation. Existing captions and recordings are kept.');return
    if result.get('files')!=[{'name':'captions.json'}] or (folder/'captions.json').stat().st_size>2*1024**2:raise ValueError('The caption worker returned an unsupported draft.')
    draft=json.loads((folder/'captions.json').read_text(encoding='utf-8'))
    items=music_planning.validate_captions(draft['items'])
    if not items or any(i['end']>snapshot['seconds']+.35 for i in items):raise ValueError('The returned caption times exceed the selected recording.')
    words=music_planning.validate_captions(draft.get('words',[]))
    if any(w['end']>snapshot['seconds']+.35 for w in words):raise ValueError('A word timestamp exceeds the recording.')
    for item in items+words:item['start']+=snapshot['offset'];item['end']+=snapshot['offset']
    similarity=None
    if snapshot.get('expected_text'):
        norm=lambda text:re.findall(r'\w+',text.casefold())
        similarity=difflib.SequenceMatcher(None,norm(snapshot['expected_text']),norm(' '.join(i['text'] for i in items))).ratio()
    source_info={'kind':'native_qwen_captions','source_asset_id':asset['id'],'source_sha256':asset['sha256'],'offset':snapshot['offset'],'word_timing':bool(words),'words':words,'note':draft['timing_note'],'expected_text_similarity':similarity}
    proposal=uid()
    db.execute('INSERT INTO caption_proposals VALUES(?,?,?,?,?,?,?,?)',(proposal,job['project_id'],job['id'],snapshot['caption_revision'],encode(items),encode(source_info),'pending',now()))
    if snapshot['test'] and (similarity is None or similarity>=.85):
        for pack in snapshot['packs']:
            if pack['pack_id']=='alignment' and not words:continue
            db.execute('INSERT OR REPLACE INTO caption_qualifications VALUES(?,?,?,?,?)',(pack['pack_id'],pack['recipe'],snapshot['hardware'],encode({'job_id':job['id'],'proposal_id':proposal,'seconds':snapshot['seconds'],'expected_text_similarity':similarity,'note':'Technical sample passed. Review recognized words and timing before applying captions.'}),now()))
    update_job(job['id'],'completed',progress=1,finished=now(),error=None)

class Request(BaseModel):
    model_config=ConfigDict(extra='forbid')
    asset_id:str
    track_id:str|None=None
    mode:str=Field(default='transcribe',pattern='^(transcribe|align)$')
    word_timing:bool=True
    text:str=Field(default='',max_length=6000)
    language:str|None=Field(default='English',max_length=100)
    test:bool=False

@router.get('/caption-tools')
async def tools(session=Depends(require_session)):
    return {'runtime_ready':bool(runtime()),'captions_ready':bool(qualification('captions')),'alignment_ready':bool(qualification('alignment')),'alignment_languages':ALIGN_LANGUAGES,'lip_sync_ready':False,'lip_sync_note':'Face lip-sync and singing mouth animation are not set up on this PC. Voice-over, song timing and captions remain available.'}
@router.post('/projects/{identifier}/captions/recognize')
async def recognize(identifier:str,body:Request,session=Depends(require_session)):return await asyncio.to_thread(queue,identifier,body.model_dump())
@router.post('/projects/{identifier}/captions/proposals/{proposal_id}/apply')
async def apply(identifier:str,proposal_id:str,session=Depends(require_session)):
    migrate();proposal=db.one("SELECT * FROM caption_proposals WHERE id=? AND project_id=? AND status='pending'",(proposal_id,identifier))
    if not proposal:raise KeyError('Caption draft not found')
    value=music_planning.save_captions(identifier,proposal['base_revision'],json.loads(proposal['body']),json.loads(proposal['source']))
    db.execute("UPDATE caption_proposals SET status='applied' WHERE id=?",(proposal_id,))
    db.execute("UPDATE caption_proposals SET status='superseded' WHERE project_id=? AND status='pending' AND base_revision<?",(identifier,value['revision']))
    return value
