"""One reviewed setup transaction: models, private programs, then a real sample."""
import asyncio,json,threading
from functools import wraps
from fastapi import APIRouter,Depends
from pydantic import BaseModel,ConfigDict
from . import model_library as models,runtime_installer as runtimes,storage,provider_workers
from .store import db,encode,uid,now
from .security import require_session

router=APIRouter(prefix='/api/setup/tools')
ALLOWED={'voices-small','music','effects','captions','alignment'}
ACTIVE={'queued','downloading','programs','testing'}
lock=threading.RLock()
def serialized(fn):
    @wraps(fn)
    def call(*args,**kwargs):
        with lock:return fn(*args,**kwargs)
    return call


def migrate():
    models.migrate();runtimes.migrate()
    with db.connect(True) as con:
        con.execute('CREATE TABLE IF NOT EXISTS tool_setup_quotes(id TEXT PRIMARY KEY,session TEXT,body TEXT,expires REAL)')
        con.execute('CREATE TABLE IF NOT EXISTS tool_setups(id TEXT PRIMARY KEY,pack_id TEXT,session TEXT,status TEXT,step TEXT,body TEXT,error TEXT,created REAL,updated REAL)')


def public(row):return {k:v for k,v in row.items() if k not in {'session','body'}}
def transactions():
    migrate();return [public(r) for r in db.all('SELECT * FROM tool_setups ORDER BY created DESC LIMIT 30')]


def quote(pack_id,session):
    migrate()
    if pack_id not in ALLOWED:raise ValueError('Choose an available preset tool. Deferred tools need a separate setup plan.')
    packs=['captions','alignment'] if pack_id=='captions' else [pack_id]
    reviews=[]
    for key in packs:
        previous=db.one('SELECT root_id FROM model_installs WHERE pack_id=? AND revision=? ORDER BY verified DESC',(key,models.pack(key)['revision']))
        reviews.append(models.quote_install(key,session,previous['root_id'] if previous else None))
    runtime_id=runtimes.PACK_RUNTIME[pack_id];runtime=runtimes.manifest(runtime_id)
    installed=db.one("SELECT * FROM provider_runtimes WHERE id=? AND state='ready'",(runtime_id,))
    ready=bool(installed and json.loads(installed['manifest'])['hash']==runtime['hash'])
    if ready:
        try:provider_workers.runtime_python(runtime_id)
        except ValueError:ready=False
    program=None if ready else runtimes.quote(runtime_id)
    model_bytes=sum(q['download_bytes'] for q in reviews);program_bytes=program['download_bytes_upper'] if program else 0
    # Worst-case combined volume need, including the cache when it is elsewhere.
    needs={}
    for q in reviews:
        anchor=storage.checked_root(q['root_id']).anchor
        needs[anchor]=needs.get(anchor,0)+q['download_bytes']
    if program:
        anchor=storage.checked_root(program['root_id']).anchor;needs[anchor]=needs.get(anchor,0)+12*1024**3
        cache=storage.role_folder('cache');needs[cache.anchor]=needs.get(cache.anchor,0)+program_bytes
    for anchor,required in needs.items():storage.require_space(anchor,required)
    value={'pack_id':pack_id,'models':reviews,'program':program,'runtime_id':runtime_id,'runtime_hash':runtime['hash'],'model_download_bytes':model_bytes,'program_download_bytes_upper':program_bytes,'download_bytes_upper':model_bytes+program_bytes,'working_bytes_by_volume':needs,'automatic_sample':pack_id in {'voices-small','music','effects'},'note':'Download and verify these pinned files, set up a private program, then make a short sample. Captions need a recording you choose in Edit. Existing ComfyUI is preserved.'}
    key=uid();db.execute('INSERT INTO tool_setup_quotes VALUES(?,?,?,?)',(key,session['hash'],encode(value),now()+1800))
    return {'id':key,**value}


@serialized
def start(quote_id,session,confirm):
    migrate()
    row=db.one('SELECT * FROM tool_setup_quotes WHERE id=? AND session=? AND expires>?',(quote_id,session['hash'],now()))
    if not confirm or not row:raise ValueError('Review the complete setup size and folders, then choose Install and test.')
    value=json.loads(row['body'])
    if runtimes.manifest(value['runtime_id'])['hash']!=value['runtime_hash']:raise ValueError('The program recipe changed. Review setup again.')
    for item in value['models']:
        if models.manifest_hash(models.pack(item['pack_id']))!=item['manifest_hash']:raise ValueError('The model pack changed. Review setup again.')
    old=db.one("SELECT * FROM tool_setups WHERE pack_id=? AND status IN ('queued','downloading','programs','testing')",(value['pack_id'],))
    if old:return public(old)
    # Start consumes the exact session-bound model reviews before they expire.
    value['download_ids']=[models.start_download(q['id'],session)['id'] for q in value['models']]
    key=uid();db.execute('INSERT INTO tool_setups VALUES(?,?,?,?,?,?,?,?,?)',(key,value['pack_id'],session['hash'],'queued','Preparing your tool.',encode(value),None,now(),now()))
    db.execute('DELETE FROM tool_setup_quotes WHERE id=?',(quote_id,))
    return public(db.one('SELECT * FROM tool_setups WHERE id=?',(key,)))


def update(identifier,status,step,body=None,error=None):
    if body is not None:db.execute('UPDATE tool_setups SET body=? WHERE id=?',(encode(body),identifier))
    db.execute('UPDATE tool_setups SET status=?,step=?,error=?,updated=? WHERE id=?',(status,step,error,now(),identifier))


@serialized
def advance(row):
    row=db.one('SELECT * FROM tool_setups WHERE id=?',(row['id'],))
    if row['status'] not in ACTIVE:return
    value=json.loads(row['body'])
    if not db.one('SELECT hash FROM sessions WHERE hash=? AND expires>?',(row['session'],now())):
        update(row['id'],'paused','Pair this browser again, then continue setup.');return
    for item in value['models']:
        if models.manifest_hash(models.pack(item['pack_id']))!=item['manifest_hash']:raise ValueError('The model recipe changed. Review a new setup before continuing.')
    if runtimes.manifest(value['runtime_id'])['hash']!=value['runtime_hash']:raise ValueError('The private program changed. Review a new setup before continuing.')
    downloads=[db.one('SELECT * FROM model_downloads WHERE id=?',(key,)) for key in value['download_ids']]
    if any(not d or d['status'] in {'failed','paused'} for d in downloads):
        update(row['id'],'paused','Download paused. Continue to reuse verified partial files.',error=next((d['error'] for d in downloads if d and d.get('error')),None));return
    if any(d['status']!='completed' for d in downloads):update(row['id'],'downloading','Downloading and verifying model files.');return
    if not value.get('runtime_job_id') and value.get('program'):
        job=runtimes.queue(value['runtime_id'],value['program']['root_id']);value['runtime_job_id']=job['id'];value['program_started']=True
        update(row['id'],'programs','Setting up this tool’s private program.',value);return
    job=db.one('SELECT * FROM runtime_install_jobs WHERE id=?',(value.get('runtime_job_id'),)) if value.get('runtime_job_id') else None
    if job and job['status'] in {'failed','needs_attention'}:raise ValueError(job['error'] or 'Program setup needs a retry.')
    if job and job['status']!='completed':update(row['id'],'programs',job['step']);return
    if not value['automatic_sample']:update(row['id'],'needs_recording','Files are ready. Open Edit → Captions, choose a recording and run the short test.');return
    if not value.get('sample_job_id'):
        from .audio_engine import queue_probe
        value['sample_job_id']=queue_probe(row['pack_id'])['job_id'];update(row['id'],'testing','Creating a short sample through the shared graphics queue.',value);return
    sample=db.one('SELECT status,error FROM jobs WHERE id=?',(value['sample_job_id'],))
    if sample['status']=='completed':update(row['id'],'ready','Sample passed. Listen before using this tool in your production.')
    elif sample['status'] in {'failed','cancelled','needs_attention'}:raise ValueError(sample['error'] or 'The sample needs another try.')
    else:update(row['id'],'testing',sample['error'] or 'Creating your sample. Other graphics work waits its turn.')


class Manager:
    task=None
    async def start(self):migrate();self.task=asyncio.create_task(self.loop())
    async def stop(self):
        if self.task:
            self.task.cancel()
            try:await self.task
            except asyncio.CancelledError:pass
    async def loop(self):
        while True:
            for row in db.all("SELECT * FROM tool_setups WHERE status IN ('queued','downloading','programs','testing') ORDER BY created"):
                try:await asyncio.to_thread(advance,row)
                except Exception as error:update(row['id'],'failed','Setup needs attention. Completed files are kept.',error=str(error)[:700])
            await asyncio.sleep(2)
manager=Manager()

class Confirm(BaseModel):
    model_config=ConfigDict(extra='forbid')
    quote_id:str
    confirm:bool=False
@router.post('/{pack_id}/quote')
async def review(pack_id:str,session=Depends(require_session)):return await asyncio.to_thread(quote,pack_id,session)
@router.post('')
async def install(body:Confirm,session=Depends(require_session)):return await asyncio.to_thread(start,body.quote_id,session,body.confirm)
@router.post('/{identifier}/continue')
async def resume(identifier:str,session=Depends(require_session)):
    row=db.one('SELECT * FROM tool_setups WHERE id=?',(identifier,))
    if not row or row['status'] not in {'failed','paused'}:raise ValueError('Choose a paused setup or one that needs attention.')
    value=json.loads(row['body'])
    if runtimes.manifest(value['runtime_id'])['hash']!=value['runtime_hash']:raise ValueError('The setup recipe changed. Review setup again.')
    for key in value['download_ids']:
        download=db.one('SELECT * FROM model_downloads WHERE id=?',(key,));body=json.loads(download['body'])
        if models.manifest_hash(models.pack(download['pack_id']))!=body['manifest_hash']:raise ValueError('The model pack changed. Review setup again.')
        if download['status'] in {'paused','failed'}:
            storage.require_space(models.install_path(models.pack(download['pack_id']),download['root_id']),max(0,download['bytes_total']-download['bytes_done']))
            body['session']=session['hash'];db.execute("UPDATE model_downloads SET status='queued',cancel_requested=0,error=NULL,body=? WHERE id=?",(encode(body),key))
    if value.get('runtime_job_id'):
        job=db.one('SELECT status FROM runtime_install_jobs WHERE id=?',(value['runtime_job_id'],))
        if job and job['status']=='needs_attention':raise ValueError('The earlier program process needs a recovery check before retrying.')
        if job and job['status']=='failed':value.pop('runtime_job_id',None)
    if value.get('sample_job_id'):
        sample=db.one('SELECT status FROM jobs WHERE id=?',(value['sample_job_id'],))
        if sample and sample['status'] in {'failed','cancelled','needs_attention'}:value.pop('sample_job_id')
    db.execute('UPDATE tool_setups SET session=? WHERE id=?',(session['hash'],identifier));update(identifier,'queued','Continuing setup with saved verified files.',value)
    return public(db.one('SELECT * FROM tool_setups WHERE id=?',(identifier,)))


@router.post('/{identifier}/pause')
async def pause(identifier:str,session=Depends(require_session)):
    def stop():
        with lock:
            row=db.one('SELECT * FROM tool_setups WHERE id=?',(identifier,))
            if not row or row['status'] not in ACTIVE:raise ValueError('This setup is not running.')
            value=json.loads(row['body'])
            for key in value['download_ids']:
                db.execute("UPDATE model_downloads SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'paused' ELSE status END WHERE id=? AND status IN ('queued','downloading','verifying')",(key,))
            update(identifier,'paused','Setup paused. A program step or sample already in progress can finish; no next step will start.')
            return {'paused':True}
    return await asyncio.to_thread(stop)
