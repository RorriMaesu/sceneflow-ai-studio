"""Locked song masters, editable sections and reviewable captions."""
import asyncio,hashlib,json,math,re,os
from fastapi import APIRouter,Depends
from pydantic import BaseModel,ConfigDict,Field
from .store import db,uid,now,encode,Conflict
from .security import require_session
from .media import asset_path,add_asset
from .config import ROOT

router=APIRouter(prefix='/api')

def migrate(store=None):
    with (store or db).connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS song_masters(scope_id TEXT PRIMARY KEY,asset_id TEXT,sha256 TEXT,revision INTEGER,body TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS song_sections(scope_id TEXT PRIMARY KEY,revision INTEGER,body TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS song_assignments(project_id TEXT PRIMARY KEY,master_hash TEXT,body TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS project_captions(project_id TEXT PRIMARY KEY,revision INTEGER,body TEXT,source TEXT,updated REAL);
        CREATE TABLE IF NOT EXISTS caption_revisions(project_id TEXT,revision INTEGER,body TEXT,source TEXT,created REAL,PRIMARY KEY(project_id,revision));
        CREATE TABLE IF NOT EXISTS caption_proposals(id TEXT PRIMARY KEY,project_id TEXT,job_id TEXT,base_revision INTEGER,body TEXT,source TEXT,status TEXT,created REAL);
        ''')

def scope(project_id):
    from .productions import membership
    db.project(project_id);member=membership(project_id,db)
    return member['root_project_id'] if member and member['purpose']=='music_video' else project_id

def song(project_id):
    migrate();key=scope(project_id)
    row=db.one('SELECT * FROM song_masters WHERE scope_id=?',(key,))
    if row:
        row['body']=json.loads(row['body'])
        asset=db.one('SELECT * FROM assets WHERE id=?',(row['asset_id'],))
        if asset:asset['metadata']=json.loads(asset['metadata'])
        row['asset']=asset
    sections=db.one('SELECT * FROM song_sections WHERE scope_id=?',(key,))
    return {'master':row,'sections':{'revision':sections['revision'],'items':json.loads(sections['body'])} if sections else {'revision':0,'items':[]}}

def verified_master(project_id):
    current=song(project_id)['master']
    if not current or not current['asset']:raise ValueError('Choose and lock a song first.')
    path=asset_path(current['asset_id'])
    with path.open('rb') as handle:
        if hashlib.file_digest(handle,'sha256').hexdigest()!=current['sha256']:raise ValueError('The song file changed. Reimport and review it before continuing.')
    return current,path

def lock_song(project_id,asset_id,revision=0,replace=False):
    migrate();key=scope(project_id)
    asset=db.one("SELECT * FROM assets WHERE id=? AND project_id=? AND kind='audio'",(asset_id,project_id))
    if not asset:raise ValueError('Choose an imported or generated recording from this sequence.')
    metadata=json.loads(asset['metadata'])
    if not .1<metadata['duration']<=1800:raise ValueError('Use a song up to 30 minutes. Split longer recordings into separate parts.')
    path=asset_path(asset_id)
    with path.open('rb') as handle:
        if hashlib.file_digest(handle,'sha256').hexdigest()!=asset['sha256']:raise ValueError('The chosen song changed on disk. Reimport it first.')
    with db.connect(True) as con:
        old=con.execute('SELECT * FROM song_masters WHERE scope_id=?',(key,)).fetchone()
        if (old['revision'] if old else 0)!=revision:raise Conflict('The song changed in another view. Refresh first.')
        if old and not replace:raise ValueError('Review replacement of the locked song before changing it.')
        con.execute('INSERT OR REPLACE INTO song_masters VALUES(?,?,?,?,?,?)',(key,asset_id,asset['sha256'],revision+1,encode({'duration':metadata['duration'],'title':metadata.get('title','Song master')}),now()))
        con.execute('INSERT OR REPLACE INTO song_sections VALUES(?,?,?,?)',(key,revision+1,'[]',now()))
    return song(project_id)

def save_sections(project_id,revision,items):
    current=song(project_id);master=current['master']
    key=scope(project_id)
    if not master:raise ValueError('Lock a song before saving its sections.')
    duration=master['body']['duration']
    if len(items)>200 or len({s['id'] for s in items})!=len(items):raise ValueError('Use up to 200 uniquely named section markers.')
    previous=0
    for item in sorted(items,key=lambda x:x['start']):
        if not all(math.isfinite(item[k]) for k in ['start','end']) or not 0<=item['start']<item['end']<=duration+.001 or item['start']<previous-.001:raise ValueError('Sections must be inside the song and must not overlap.')
        previous=item['end']
    with db.connect(True) as con:
        row=con.execute('SELECT revision FROM song_sections WHERE scope_id=?',(key,)).fetchone()
        if not row or row['revision']!=revision:raise Conflict('Song markers changed. Refresh before saving.')
        con.execute('UPDATE song_sections SET revision=revision+1,body=?,updated=? WHERE scope_id=?',(encode(sorted(items,key=lambda x:x['start'])),now(),key))
    return song(project_id)

def place_song(project_id,start=0,end=None,fit_video=False):
    from .exports import save_timeline
    master,path=verified_master(project_id);p=db.project(project_id);timeline=p['timeline']
    if not timeline['clips']:raise ValueError('Add pictures or video to the edit first.')
    end=master['body']['duration'] if end is None else end
    if not 0<=start<end<=master['body']['duration']+.001:raise ValueError('Choose a section inside the locked song.')
    asset=master['asset']
    if asset['project_id']!=project_id:
        existing=db.one("SELECT * FROM assets WHERE project_id=? AND kind='audio' AND json_extract(metadata,'$.song_master_source_id')=? AND sha256=?",(project_id,master['asset_id'],master['sha256']))
        asset=existing or add_asset(project_id,None,None,'audio',path,extra={'role':'music','song_master_source_id':master['asset_id'],'song_master_sha256':master['sha256']})
    clips=timeline['clips']
    if fit_video:
        fps=timeline['settings'].get('fps',30);remaining=round((end-start)*fps);fitted=[]
        for clip in clips:
            available=int((float(clip['trim_out'])-float(clip.get('trim_in',0)))/float(clip.get('speed',1))*fps+1e-6)
            use=min(remaining,available)
            if use>0:
                fitted.append({**clip,'trim_out':float(clip.get('trim_in',0))+use/fps*float(clip.get('speed',1)),'transition':'cut'})
                remaining-=use
            if remaining<=0:break
        if remaining>0:raise ValueError(f'Add {remaining/fps:.2f} more seconds of visuals, or choose a shorter song section. The song will not be sped up or cut short.')
        target=round((end-start)*fps)/fps
        if any(t.get('role') in {'voiceover','effects'} and not t.get('mute') and t.get('start',0)+t['trim_out']-t.get('trim_in',0)>target+1/fps for t in timeline.get('audio',[])):raise ValueError('A speech or effects track extends past this song section. Adjust it or choose a longer section first.')
        clips=fitted
    audio=[]
    for track in timeline.get('audio',[]):
        original=db.one('SELECT sha256 FROM assets WHERE id=?',(track['asset_id'],))
        if not track.get('locked_song') and not (track.get('role')=='music' and original and original['sha256']==master['sha256']):audio.append(track)
    audio.append({'id':uid(),'asset_id':asset['id'],'trim_in':start,'trim_out':end,'start':0,'role':'music','volume':1,'mute':False,'fade_in':0,'fade_out':0,'duck':False,'locked_song':True,'song_sha256':master['sha256']})
    settings={**timeline['settings'],'audio_mode':'mixed'}
    if fit_video:settings.update(transition='cut',loop='none',repeats=1)
    return save_timeline(project_id,timeline['revision'],clips,audio,settings)

def assign_section(project_id,start,end,theme=''):
    master,_=verified_master(project_id);key=scope(project_id)
    if not 0<=start<end<=master['body']['duration']+.001:raise ValueError('Choose a section inside the locked song.')
    if end-start>160:raise ValueError('Split this section into parts up to 160 seconds, then plan one sequence at a time.')
    body={'start':start,'end':end,'target_seconds':end-start,'theme':theme,'song_title':master['body']['title']}
    with db.connect(True) as con:
        current=con.execute('SELECT sha256 FROM song_masters WHERE scope_id=?',(key,)).fetchone()
        if not current or current['sha256']!=master['sha256']:raise Conflict('The song changed while this section was selected. Choose it again.')
        con.execute('INSERT OR REPLACE INTO song_assignments VALUES(?,?,?,?)',(project_id,master['sha256'],encode(body),now()))
    return body

def context(project_id,store=None):
    from .productions import membership
    store=store or db
    if not store.one("SELECT name FROM sqlite_master WHERE type='table' AND name='song_masters'"):return None
    member=membership(project_id,store)
    key=member['root_project_id'] if member and member['purpose']=='music_video' else project_id
    master=store.one('SELECT * FROM song_masters WHERE scope_id=?',(key,))
    if not master:return None
    selected=store.one('SELECT * FROM song_assignments WHERE project_id=? AND master_hash=?',(project_id,master['sha256']))
    result={'song':json.loads(master['body']),'source_sha256':master['sha256'],'section':json.loads(selected['body']) if selected else None,'note':'Plan visuals around the locked audio. Do not invent face lip-sync or regenerate the song.'}
    return result

def captions(project_id,store=None):
    store=store or db
    migrate(store);store.project(project_id)
    row=store.one('SELECT * FROM project_captions WHERE project_id=?',(project_id,))
    return {'revision':row['revision'],'items':json.loads(row['body']),'source':json.loads(row['source'])} if row else {'revision':0,'items':[],'source':{}}

def validate_captions(items):
    if len(items)>10000:raise ValueError('Use up to 10,000 caption entries per sequence.')
    for item in items:
        if not all(isinstance(item.get(k),(int,float)) and math.isfinite(item[k]) for k in ['start','end']) or not 0<=item['start']<item['end']<=36000 or not isinstance(item.get('text'),str) or not 0<len(item['text'])<=1000 or '\x00' in item['text']:raise ValueError('Each caption needs text and valid start/end times.')
    return sorted(items,key=lambda x:(x['start'],x['end']))

def save_captions(project_id,revision,items,source=None):
    migrate();db.project(project_id);items=validate_captions(items)
    with db.connect(True) as con:
        old=con.execute('SELECT * FROM project_captions WHERE project_id=?',(project_id,)).fetchone()
        if (old['revision'] if old else 0)!=revision:raise Conflict('Captions changed in another view. Refresh before saving.')
        if old:con.execute('INSERT OR IGNORE INTO caption_revisions VALUES(?,?,?,?,?)',(project_id,revision,old['body'],old['source'],now()))
        con.execute('INSERT OR REPLACE INTO project_captions VALUES(?,?,?,?,?)',(project_id,revision+1,encode(items),encode(source or {'kind':'manual'}),now()))
    return captions(project_id)

def script_captions(project_id,revision):
    from .script_audio import view
    rows=view(project_id)['lines'];items=[]
    for line in rows:
        asset=db.one("SELECT metadata,sha256 FROM assets WHERE id=? AND project_id=? AND kind='audio'",(line['selected_asset_id'],project_id)) if line['selected_asset_id'] else None
        if not asset:raise ValueError('Record each current script line before using its timing for captions.')
        items.append({'start':line['start'],'end':line['start']+json.loads(asset['metadata'])['duration'],'text':line['text']})
    if not items:raise ValueError('Add and record some script lines first.')
    return save_captions(project_id,revision,items,{'kind':'recorded_script','note':'Line timing uses real recording lengths. Word-level timing has not been inferred.'})

def stamp(seconds,vtt=False):
    value=round(seconds*1000);hours,value=divmod(value,3600000);minutes,value=divmod(value,60000);seconds,ms=divmod(value,1000)
    return f'{hours:02}:{minutes:02}:{seconds:02}{"." if vtt else ","}{ms:03}'

def subtitle_text(items,vtt=False):
    items=validate_captions(items)
    return ('WEBVTT\n\n' if vtt else '')+'\n\n'.join((('' if vtt else str(i+1)+'\n')+stamp(item['start'],vtt)+' --> '+stamp(item['end'],vtt)+'\n'+item['text'].replace('\r','')) for i,item in enumerate(items))+'\n'

def parse_subtitles(text):
    if len(text.encode('utf-8'))>1024**2:raise ValueError('Import a subtitle file up to 1 MB; split larger files by sequence.')
    def seconds(value):
        match=re.fullmatch(r'(?:(\d{1,2}):)?(\d{2}):(\d{2})[.,](\d{1,3})',value)
        if not match or int(match[2])>=60 or int(match[3])>=60:raise ValueError('Use standard SRT or VTT caption times.')
        return int(match[1] or 0)*3600+int(match[2])*60+int(match[3])+int(match[4])/10**len(match[4])
    items=[]
    for block in re.split(r'\n\s*\n',text.lstrip('\ufeff').replace('\r\n','\n').strip()):
        if not block.strip() or block.startswith(('WEBVTT','NOTE')):continue
        lines=block.splitlines();index=next((i for i,line in enumerate(lines) if '-->' in line),None)
        if index is None:raise ValueError('This subtitle block has no valid caption time.')
        a,b=lines[index].split('-->',1)
        if not b.strip():raise ValueError('A subtitle entry is missing its end time.')
        items.append({'start':seconds(a.strip()),'end':seconds(b.strip().split()[0]),'text':'\n'.join(lines[index+1:]).strip()})
    if not items:raise ValueError('No caption entries were found in this subtitle file.')
    return validate_captions(items)

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid')
class Song(Strict):
    asset_id:str
    revision:int=0
    replace:bool=False
class Section(Strict):
    id:str=Field(min_length=1,max_length=100)
    label:str=Field(min_length=1,max_length=100)
    start:float=Field(ge=0,allow_inf_nan=False)
    end:float=Field(gt=0,allow_inf_nan=False)
class Sections(Strict):
    revision:int
    items:list[Section]=Field(max_length=200)
class Placement(Strict):
    start:float=Field(default=0,ge=0,allow_inf_nan=False)
    end:float|None=Field(default=None,gt=0,allow_inf_nan=False)
    fit_video:bool=False
class Assignment(Strict):
    start:float=Field(ge=0,allow_inf_nan=False)
    end:float=Field(gt=0,allow_inf_nan=False)
    theme:str=Field(default='',max_length=4000)
class Caption(Strict):
    start:float=Field(ge=0,allow_inf_nan=False)
    end:float=Field(gt=0,allow_inf_nan=False)
    text:str=Field(min_length=1,max_length=1000)
class Captions(Strict):
    revision:int
    items:list[Caption]=Field(max_length=10000)
    include_mp4:bool=False
class Revision(Strict):
    revision:int
class ImportSubtitles(Strict):
    revision:int
    text:str=Field(max_length=1024**2)

@router.get('/projects/{identifier}/song')
async def get_song(identifier:str,session=Depends(require_session)):return song(identifier)
@router.post('/projects/{identifier}/song')
async def set_song(identifier:str,body:Song,session=Depends(require_session)):return await asyncio.to_thread(lock_song,identifier,**body.model_dump())
@router.post('/projects/{identifier}/song/sections')
async def sections(identifier:str,body:Sections,session=Depends(require_session)):return save_sections(identifier,body.revision,[x.model_dump() for x in body.items])
@router.post('/projects/{identifier}/song/place')
async def place(identifier:str,body:Placement,session=Depends(require_session)):return await asyncio.to_thread(place_song,identifier,**body.model_dump())
@router.post('/projects/{identifier}/song/assignment')
async def assign(identifier:str,body:Assignment,session=Depends(require_session)):return await asyncio.to_thread(assign_section,identifier,**body.model_dump())
@router.get('/projects/{identifier}/captions')
async def get_captions(identifier:str,session=Depends(require_session)):
    current=captions(identifier)
    current['proposals']=[{**r,'body':json.loads(r['body']),'source':json.loads(r['source'])} for r in db.all("SELECT * FROM caption_proposals WHERE project_id=? AND status='pending' ORDER BY created DESC",(identifier,))]
    return current
@router.post('/projects/{identifier}/captions')
async def set_captions(identifier:str,body:Captions,session=Depends(require_session)):
    old=captions(identifier);items=[x.model_dump() for x in body.items]
    source={**old['source'],'include_mp4':body.include_mp4}
    if old['items']!=items:source.update(kind='manual',word_timing=False,words=[])
    return save_captions(identifier,body.revision,items,source)
@router.post('/projects/{identifier}/captions/from-script')
async def from_script(identifier:str,body:Revision,session=Depends(require_session)):return script_captions(identifier,body.revision)
@router.post('/projects/{identifier}/captions/import')
async def import_subtitles(identifier:str,body:ImportSubtitles,session=Depends(require_session)):
    previous=captions(identifier)
    return save_captions(identifier,body.revision,parse_subtitles(body.text),{'kind':'imported_subtitles','include_mp4':previous['source'].get('include_mp4',False)})
@router.get('/projects/{identifier}/captions/text')
async def caption_text(identifier:str,format:str='srt',session=Depends(require_session)):
    if format not in ['srt','vtt']:raise ValueError('Choose SRT or VTT subtitles.')
    current=captions(identifier)
    if not current['items']:raise ValueError('Save some captions before downloading a subtitle file.')
    text=subtitle_text(current['items'],format=='vtt')
    from . import storage
    from uuid import uuid5,NAMESPACE_URL
    digest=hashlib.sha256(text.encode('utf-8')).hexdigest();file_id=str(uuid5(NAMESPACE_URL,identifier+':'+str(current['revision'])+':'+format+':'+digest))
    location=storage.media_location(identifier,None,'export',file_id,'.'+format)
    destination=location[1] if location else ROOT/'projects'/identifier/'exports'/(file_id+'.'+format)
    storage.reject_links(destination);destination.parent.mkdir(parents=True,exist_ok=True);storage.require_space(destination.parent,len(text.encode('utf-8')))
    if destination.exists() and destination.read_text(encoding='utf-8')!=text:destination=destination.with_name(uid()+'.'+format)
    if not destination.exists():
        temporary=destination.with_name(destination.name+'.'+uid()+'.part');temporary.write_text(text,encoding='utf-8');os.replace(temporary,destination)
    return {'text':text,'filename':'captions.'+format,'saved_to':str(destination)}


def bundle_snapshot(con,project_id):
    if not con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='project_captions'").fetchone():return None
    key=project_id
    if con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='production_sequences'").fetchone():
        member=con.execute("SELECT p.root_project_id FROM production_sequences s JOIN production_episodes e ON e.id=s.episode_id JOIN productions p ON p.id=e.production_id WHERE s.project_id=? AND p.purpose='music_video'",(project_id,)).fetchone()
        if member:key=member[0]
    def one(sql,values):
        row=con.execute(sql,values).fetchone();return dict(row) if row else None
    master=one('SELECT * FROM song_masters WHERE scope_id=?',(key,))
    return {'captions':one('SELECT * FROM project_captions WHERE project_id=?',(project_id,)),
            'caption_history':[dict(r) for r in con.execute('SELECT * FROM caption_revisions WHERE project_id=? ORDER BY revision',(project_id,))],
            'master':master,'sections':one('SELECT * FROM song_sections WHERE scope_id=?',(key,)),
            'assignment':one('SELECT * FROM song_assignments WHERE project_id=?',(project_id,)),
            'source_asset':one('SELECT * FROM assets WHERE id=?',(master['asset_id'],)) if master else None}


def restore_snapshot(con,value,mapping,project_id,assets,insert,remap):
    if value is None:return
    if not isinstance(value,dict) or not {'captions','caption_history','master','sections','source_asset'}<=set(value) or set(value)-{'captions','caption_history','master','sections','source_asset','assignment'}:raise ValueError('Unsupported bundled song or caption data.')
    if value['master']:
        master=value['master'];asset=assets.get(master['asset_id'])
        if not asset or asset['kind']!='audio' or asset['sha256']!=master['sha256']:raise ValueError('The bundled song has no matching verified audio file.')
        duration=json.loads(asset['metadata'])['duration']
        if abs(float(json.loads(master['body'])['duration'])-duration)>.1:raise ValueError('The bundled song duration does not match its audio.')
        if value['sections']:
            try:
                items=json.loads(value['sections']['body'])
                if not isinstance(items,list) or len(items)>200 or len({s['id'] for s in items})!=len(items):raise ValueError()
                previous=0
                for item in sorted(items,key=lambda s:s['start']):
                    if not isinstance(item['label'],str) or len(item['label'])>100 or not all(math.isfinite(item[k]) for k in ['start','end']) or not previous<=item['start']<item['end']<=duration+.1:raise ValueError()
                    previous=item['end']
            except (TypeError,KeyError,ValueError):raise ValueError('The bundled song section markers are invalid.')
    for old in [value['captions'],*value['caption_history']]:
        if old:validate_captions(json.loads(old['body']))
    for table,rows in [('project_captions',[value['captions']]),('caption_revisions',value['caption_history']),('song_masters',[value['master']]),('song_sections',[value['sections']]),('song_assignments',[value.get('assignment')])]:
        for old in rows:
            if not old:continue
            row=remap(old,mapping)
            if 'project_id' in row:row['project_id']=project_id
            if 'scope_id' in row:row['scope_id']=project_id
            for key in ['body','source']:
                if key in row:row[key]=encode(remap(json.loads(row[key]),mapping))
            insert(table,row)
