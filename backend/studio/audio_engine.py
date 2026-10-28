"""Typed local sound jobs, pack integrity and hardware-specific qualification."""
import asyncio
import ast
import hashlib
import json
from pathlib import Path

from . import model_library, provider_workers, storage
from .config import settings
from .resources import resources
from .store import db, encode, now, uid

GIB = 1024 ** 3
def adapter_hash(pack_id):
    tree=ast.parse((Path(__file__).resolve().parents[1]/'provider_worker.py').read_text(encoding='utf-8'))
    operation=PROVIDERS[pack_id]['kind']
    names={'offline','save_audio','graphics_budget','main',operation}|({'chunks'} if operation=='speech' else {'music_view'} if operation=='music' else set())
    recipe=[ast.dump(node,include_attributes=False) for node in tree.body if isinstance(node,(ast.Import,ast.ImportFrom)) or isinstance(node,ast.FunctionDef) and node.name in names]
    return hashlib.sha256(encode(recipe).encode()).hexdigest()
PROVIDERS = {
    'voices-small': {'runtime': 'speech', 'kind': 'speech', 'role': 'voiceover', 'gpu_free': 6*GIB, 'ram_free': 6*GIB, 'max_seconds': 30, 'max_chars': 600, 'instructions': False},
    'voices-character': {'runtime': 'speech', 'kind': 'speech', 'role': 'voiceover', 'gpu_free': 8*GIB, 'ram_free': 8*GIB, 'max_seconds': 30, 'max_chars': 600, 'instructions': False},
    'music': {'runtime': 'music', 'kind': 'music', 'role': 'music', 'gpu_free': 11*GIB, 'ram_free': 9*GIB, 'max_seconds': 240},
    'effects': {'runtime': 'effects', 'kind': 'effects', 'role': 'effects', 'gpu_free': 10*GIB, 'ram_free': 10*GIB, 'max_seconds': 10},
}
LANGUAGES = ('English','Chinese','Japanese','Korean','German','French','Russian','Portuguese','Spanish','Italian')
VOICES = {'Ryan':'English · male','Aiden':'English · male','Vivian':'Multilingual · female','Serena':'Multilingual · female','Dylan':'Multilingual · male','Eric':'Multilingual · male','Uncle_Fu':'Multilingual · male','Ono_Anna':'Japanese · female','Sohee':'Korean · female'}


def migrate():
    with db.connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS audio_qualifications(pack_id TEXT,revision TEXT,runtime_hash TEXT,hardware TEXT,body TEXT,created REAL,PRIMARY KEY(pack_id,revision,runtime_hash,hardware));
        CREATE TABLE IF NOT EXISTS audio_setup_project(id TEXT PRIMARY KEY);
        ''')


def fingerprint():
    telemetry=resources()
    gpu=telemetry.get('gpu') or {}
    driver='unknown'
    try:
        import pynvml
        pynvml.nvmlInit();driver=pynvml.nvmlSystemGetDriverVersion()
    except Exception:pass
    value={'name':gpu.get('name'),'total':gpu.get('total'),'driver':driver}
    return hashlib.sha256(encode(value).encode()).hexdigest()


def runtime_record(pack_id):
    from .runtime_installer import manifest
    provider_workers.migrate()
    spec=PROVIDERS[pack_id]
    row=db.one("SELECT * FROM provider_runtimes WHERE id=? AND state='ready'",(spec['runtime'],))
    if not row or json.loads(row['manifest']).get('hash')!=manifest(spec['runtime'])['hash']:
        return None
    return row


def qualification(pack_id):
    migrate();provider_workers.migrate()
    if pack_id not in PROVIDERS:return None
    runtime=runtime_record(pack_id)
    if not runtime:return None
    value=model_library.pack(pack_id)
    row=db.one('SELECT * FROM audio_qualifications WHERE pack_id=? AND revision=? AND runtime_hash=? AND hardware=?',
               (pack_id,value['revision'],json.loads(runtime['manifest'])['hash'],fingerprint()))
    if row:
        row['body']=json.loads(row['body'])
        if row['body'].get('adapter_hash')!=adapter_hash(pack_id):return None
        if not row['body'].get('elapsed_seconds') and row['body'].get('job_id'):
            timing=db.one('SELECT started,finished FROM jobs WHERE id=?',(row['body']['job_id'],))
            if timing and timing['started'] and timing['finished']:row['body']['elapsed_seconds']=round(timing['finished']-timing['started'],1)
    return row


def pack_ready(pack_id):
    return qualification(pack_id) is not None


def installed_pack(pack_id):
    model_library.migrate()
    value=model_library.pack(pack_id)
    row=db.one('SELECT * FROM model_installs WHERE pack_id=? AND revision=? ORDER BY verified DESC',(pack_id,value['revision']))
    if not row:raise ValueError('Download this tool’s model files in Setup first.')
    return value,row,model_library.install_path(value,row['root_id'])


def files_unchanged(value, row, fingerprints=None):
    recorded=fingerprints or json.loads(row['body']).get('fingerprints',{})
    current={}
    for item in value['files']:
        path=model_library.file_path(value,row['root_id'],item)
        info=path.stat()
        stamp=[info.st_size,info.st_mtime_ns]
        if recorded.get(item['path'])!=stamp and not model_library.matches(path,item):
            raise ValueError('A model file changed or is incomplete. Repair its download before continuing.')
        current[item['path']]=stamp
    return current


def setup_project():
    migrate()
    row=db.one('SELECT id FROM audio_setup_project LIMIT 1')
    if row:return row['id']
    project=db.create_project('Studio sound samples',mode='manual',settings={'setup_samples':True,'auto_export':False})
    db.execute('UPDATE projects SET archived=1 WHERE id=?',(project['id'],))
    db.execute('INSERT INTO audio_setup_project VALUES(?)',(project['id'],))
    return project['id']


def queue_sound(project_id,pack_id,inputs,scene_id=None,setup_probe=False,automatic=False):
    from .production import queue_snapshot
    from .runtime_installer import manifest
    migrate();provider_workers.migrate()
    if pack_id not in PROVIDERS:raise ValueError('Choose a supported local sound tool.')
    spec=PROVIDERS[pack_id]
    value,installed,folder=installed_pack(pack_id)
    runtime=runtime_record(pack_id)
    if not runtime:raise ValueError('Finish setting up this tool’s program files in Setup.')
    measured=qualification(pack_id)
    if not setup_probe and not measured:raise ValueError('Run this tool’s short sample test in Setup before using it in a production.')
    if scene_id and db.scene(scene_id)['project_id']!=project_id:raise ValueError('Choose a scene from this production.')
    text=str(inputs.get('text',''))
    if spec['kind']=='speech':
        if not text.strip() or len(text)>spec['max_chars']:raise ValueError('Split this speech into lines of at most 600 characters.')
        if inputs.get('language','English') not in LANGUAGES:raise ValueError('Choose a language supported by this voice tool.')
        if pack_id=='voices-small' and inputs.get('voice','Ryan') not in VOICES:raise ValueError('Choose one of the installed preset voices.')
        if inputs.get('delivery') and not spec['instructions']:raise ValueError('This voice tool uses preset delivery. Clear acting instructions or choose an expressive voice tool.')
    else:
        if pack_id=='music' and not inputs.get('instrumental',True) and not setup_probe and 'vocal' not in measured['body'].get('capabilities',[]):raise ValueError('Run the singing sample in Setup before creating a song with vocals.')
        duration=inputs.get('seconds',5)
        limit=min(spec['max_seconds'],measured['body'].get('tested_seconds') or spec['max_seconds']) if measured and not setup_probe else spec['max_seconds']
        if pack_id=='music' and measured and not setup_probe:limit=min(spec['max_seconds'],measured['body'].get('tested_lengths',{}).get('instrumental' if inputs.get('instrumental',True) else 'vocal',limit))
        if not isinstance(duration,(int,float)) or not 1<=duration<=limit:raise ValueError(f'This PC has passed cues up to {limit} seconds. Use that length or run a longer sample test in Setup.')
        if not str(inputs.get('prompt','')).strip() or len(inputs['prompt'])>2000:raise ValueError('Describe the sound in up to 2000 characters.')
        if len(str(inputs.get('lyrics','')))>6000:raise ValueError('Keep the lyrics under 6000 characters.')
    # Integrity reads run in the queued job, never in a browser request on a busy media disk.
    fingerprints=measured['body'].get('fingerprints',{}) if measured else {}
    if setup_probe and not fingerprints:
        previous=db.one('SELECT body FROM audio_qualifications WHERE pack_id=? AND revision=? ORDER BY created DESC LIMIT 1',(pack_id,value['revision']))
        if previous:fingerprints=json.loads(previous['body']).get('fingerprints',{})
    profile={'gpu_free':spec['gpu_free'],'ram_free':spec['ram_free'],'basis':'Short setup probe; fit is not assumed until this exact profile succeeds.' if setup_probe else 'Qualified local sound profile; exact model/runtime/hardware revisions are frozen.'}
    if measured:profile=measured['body']['profile']
    snapshot={'project_id':project_id,'scene_id':scene_id,'pack_id':pack_id,'pack_revision':value['revision'],'root_id':installed['root_id'],
              'runtime_id':spec['runtime'],'runtime_hash':json.loads(runtime['manifest'])['hash'],'hardware':fingerprint(),
              'adapter_hash':adapter_hash(pack_id),
              'inputs':inputs,'role':spec['role'],'resource_profile':profile,'setup_probe':setup_probe,'fingerprints':fingerprints,
              'manual_override':not automatic,'manual_requested_at':now(),'automatic':automatic}
    job=queue_snapshot(spec['kind'],snapshot,automatic=automatic,force=setup_probe)
    return {'job_id':job['id']}


def queue_probe(pack_id, seconds=None, vocal=False):
    migrate()
    if pack_id=='voices-character':raise ValueError('Choose a reference recording in Cast & voices before testing a character voice.')
    inputs={'text':'Welcome to SceneFlow. Your story begins here.','language':'English','voice':'Ryan','seed':26102026} if pack_id=='voices-small' else {'prompt':'Warm gentle piano and soft strings, instrumental, no vocals','seconds':10,'instrumental':True,'seed':26102026} if pack_id=='music' else {'prompt':'Gentle rain pattering on a window, no music and no speech','seconds':3,'seed':26102026}
    if seconds is not None and pack_id in {'music','effects'}:inputs['seconds']=seconds
    if vocal and pack_id=='music':inputs.update(prompt='A warm clear English vocal over gentle piano, simple pop song',lyrics='[Verse]\nEvery story starts with a light\nEvery dream can wake tonight',instrumental=False,seconds=seconds or 15)
    for existing in db.all("SELECT id,snapshot FROM jobs WHERE kind IN ('speech','music','effects') AND status IN ('queued','running') AND json_extract(snapshot,'$.setup_probe')=1 AND json_extract(snapshot,'$.pack_id')=?",(pack_id,)):
        if json.loads(existing['snapshot'])['inputs']==inputs:return {'job_id':existing['id']}
    return queue_sound(setup_project(),pack_id,inputs,setup_probe=True)


async def execute(job,snapshot):
    from .production import update_job
    from .media import add_asset,asset_path
    migrate()
    value,installed,folder=installed_pack(snapshot['pack_id'])
    runtime=runtime_record(snapshot['pack_id'])
    if value['revision']!=snapshot['pack_revision'] or not runtime or json.loads(runtime['manifest'])['hash']!=snapshot['runtime_hash'] or fingerprint()!=snapshot['hardware'] or snapshot.get('adapter_hash')!=adapter_hash(snapshot['pack_id']):
        raise ValueError('This tool or graphics setup changed. Run its sample test again before retrying.')
    update_job(job['id'],'running',started=now(),progress=.01,error=None)
    fingerprints=await asyncio.to_thread(files_unchanged,value,installed,snapshot['fingerprints'])
    if db.one('SELECT cancel_requested FROM jobs WHERE id=?',(job['id'],))['cancel_requested']:
        update_job(job['id'],'cancelled',finished=now(),error='Stopped before loading the sound model.');return
    inputs={**snapshot['inputs'],'provider':PROVIDERS[snapshot['pack_id']]['kind'],'pack_id':snapshot['pack_id'],'pack_path':str(folder)}
    if snapshot['pack_id']=='music':
        inputs['model_view']=str(storage.child(installed['root_id'],'sceneflow/runtimes/model-views/music/'+snapshot['runtime_hash']+'/.directory',True).parent)
    if inputs.get('reference_asset_id'):
        reference=db.one('SELECT * FROM assets WHERE id=? AND project_id=? AND kind=?',(inputs['reference_asset_id'],job['project_id'],'audio'))
        if not reference:raise ValueError('This voice recording must belong to the current production.')
        path=asset_path(reference['id'])
        with path.open('rb') as handle:
            if hashlib.file_digest(handle,'sha256').hexdigest()!=inputs['reference_sha256']:raise ValueError('The voice reference changed on disk.')
        inputs['reference_path']=str(path)
    update_job(job['id'],'running',progress=.03,error=None)
    try:
        result,work=await provider_workers.run(job,snapshot['runtime_id'],inputs,timeout=1800)
    except ValueError as error:
        if 'out of memory' in str(error).lower():
            raise ValueError('This sound setting reached the graphics memory limit and was stopped. Earlier takes are safe. Use a shorter cue or run the lighter setup sample before retrying.') from error
        raise
    except provider_workers.CreationCancelled:
        update_job(job['id'],'cancelled',finished=now(),error='This sound task was cancelled. Earlier takes are kept.')
        return
    files=result.get('files',[])
    if not files:raise ValueError('The sound tool returned no audio file.')
    assets=[]
    for item in files:
        path=work/item['name']
        if path.suffix.lower() not in {'.wav','.flac'}:raise ValueError('The sound tool returned an unsupported audio file.')
        asset=await asyncio.to_thread(add_asset,job['project_id'],job['scene_id'],job['id'],'audio',path,None,
                                     {'role':snapshot['role'],'pack_id':snapshot['pack_id'],'pack_revision':snapshot['pack_revision'],'runtime_hash':snapshot['runtime_hash'],'seed':snapshot['inputs'].get('seed'),'script_line_id':snapshot['inputs'].get('line_id'),'script_revision':snapshot['inputs'].get('line_revision'),'setup_sample':bool(snapshot['setup_probe'])})
        metadata=json.loads(asset['metadata'])
        if not .1<metadata['duration']<300 or metadata['audio_streams']!=1:raise ValueError('The generated sound did not pass the duration/audio-track check.')
        if snapshot['inputs'].get('seconds') and abs(metadata['duration']-snapshot['inputs']['seconds'])>.35:raise ValueError('The sound duration did not match the requested cue. The take is kept for review.')
        assets.append(asset)
    if snapshot['setup_probe']:
        from .resource_broker import broker
        broker.sample()
        observed=broker.measurement or {}
        profile={**snapshot['resource_profile'],'basis':'Minimum free memory includes the conservative floor and sampled setup growth with 10% allowance; the display reserve is additional.'}
        for key,peak,initial in [('gpu_free','gpu_used_peak','gpu_used_start'),('ram_free','ram_used_peak','ram_used_start')]:
            if initial in observed:profile[key]=max(profile[key],int(max(0,observed[peak]-observed[initial])*1.1))
        previous=qualification(snapshot['pack_id'])
        capabilities=set((previous or {}).get('body',{}).get('capabilities',[]))
        capabilities.add('vocal' if snapshot['pack_id']=='music' and not snapshot['inputs'].get('instrumental',True) else 'instrumental' if snapshot['pack_id']=='music' else snapshot['pack_id'])
        seconds=snapshot['inputs'].get('seconds')
        lengths={**(previous or {}).get('body',{}).get('tested_lengths',{})}
        if seconds:lengths['vocal' if not snapshot['inputs'].get('instrumental',True) else 'instrumental']=seconds
        started=db.one('SELECT started FROM jobs WHERE id=?',(job['id'],))['started']
        body={'fingerprints':fingerprints,'asset_id':assets[0]['id'],'job_id':job['id'],'elapsed_seconds':round(now()-started,1) if started else None,'profile':profile,'adapter_hash':snapshot['adapter_hash'],'capabilities':sorted(capabilities),'tested_lengths':lengths,
              'tested_seconds':min(lengths.values()) if lengths else None, 'note':'Technical sample passed on this PC. Listen to the sample; creative quality and other languages/durations are not certified by decoding.'}
        db.execute('INSERT OR REPLACE INTO audio_qualifications VALUES(?,?,?,?,?,?)',(snapshot['pack_id'],snapshot['pack_revision'],snapshot['runtime_hash'],snapshot['hardware'],encode(body),now()))
    else:
        from .script_audio import apply_take
        apply_take(job,snapshot,assets[0])
    update_job(job['id'],'completed',progress=1,finished=now(),error=None)
