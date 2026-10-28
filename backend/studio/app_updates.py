"""Explicit metadata check, verified staging, and idle-only application updates."""
import asyncio,json,os,re,subprocess,sys
from pathlib import Path
import httpx,psutil
from fastapi import APIRouter,Depends,BackgroundTasks
from pydantic import BaseModel,ConfigDict
from .config import ROOT,VERSION
from .store import db,encode,now,uid
from .security import require_session
from . import storage
from update_package import extract,digest,validate,version

router=APIRouter(prefix='/api/app-updates')
REPO='RorriMaesu/sceneflow-ai-studio'

def migrate():db.execute('CREATE TABLE IF NOT EXISTS app_update_quotes(id TEXT PRIMARY KEY,session TEXT,body TEXT,expires REAL)')
def plan_path():return ROOT/'local'/'app-update.json'
def read_plan():return json.loads(plan_path().read_text(encoding='utf-8')) if plan_path().exists() else None
def write_plan(value):
    from apply_update import save
    path=plan_path();path.parent.mkdir(parents=True,exist_ok=True);storage.reject_links(path);save(path,value)

def idle():
    if db.one("SELECT id FROM jobs WHERE status IN ('queued','running','submitted','reconciling') LIMIT 1"):raise ValueError('Finish or stop queued and active creation work before restarting Studio for an update.')
    for table,statuses in [('model_downloads',('queued','downloading','verifying')),('runtime_install_jobs',('queued','installing')),('tool_setups',('queued','downloading','programs','testing'))]:
        if db.one("SELECT name FROM sqlite_master WHERE type='table' AND name=?",(table,)) and db.one('SELECT id FROM '+table+' WHERE status IN ('+','.join('?' for _ in statuses)+') LIMIT 1',statuses):raise ValueError('Finish or pause tool setup and downloads before updating Studio.')

async def fetch(url,limit,expected=None):
    data=bytearray()
    async with httpx.AsyncClient(timeout=120,follow_redirects=True,trust_env=False) as client:
        async with client.stream('GET',url,headers={'Accept':'application/vnd.github+json','User-Agent':'SceneFlow-Studio'}) as response:
            if response.status_code==404:return None
            response.raise_for_status()
            async for block in response.aiter_bytes(1024**2):
                data.extend(block)
                if len(data)>limit:raise ValueError('The update response exceeded its reviewed size.')
    if expected is not None and len(data)!=expected:raise ValueError('The update download size changed. Check for updates again.')
    return bytes(data)

@router.get('')
async def status(session=Depends(require_session)):
    plan=read_plan()
    return {'installed':VERSION,'update':{k:plan.get(k) for k in ['id','version','old_version','state','error','release_url']} if plan else None}

@router.post('/check')
async def check(session=Depends(require_session)):
    migrate();raw=await fetch(f'https://api.github.com/repos/{REPO}/releases/latest',1024**2)
    if raw is None:return {'installed':VERSION,'available':False,'message':'No packaged Windows release is published yet. Your installed tools stay available.'}
    release=json.loads(raw);tag=release['tag_name'].removeprefix('v');version(tag)
    if release.get('draft') or release.get('prerelease') or version(tag)<=version(VERSION):return {'installed':VERSION,'available':False,'message':'This application is current.'}
    filename='SceneFlow-'+tag+'-Windows.zip';asset=next((a for a in release['assets'] if a['name']==filename),None)
    checksum=next((a for a in release['assets'] if a['name']==filename+'.sha256'),None)
    prefix=f'https://github.com/{REPO}/releases/download/v{tag}/'
    if not asset or not checksum or not 0<asset['size']<=30*1024**2 or asset['browser_download_url']!=prefix+filename or checksum['browser_download_url']!=prefix+filename+'.sha256':raise ValueError('This release has no supported verified Windows package. Use its release page for details.')
    raw=await fetch(checksum['browser_download_url'],1024)
    sha=(raw or b'').decode('ascii').split()[0]
    if not re.fullmatch('[0-9a-f]{64}',sha):raise ValueError('The release checksum is invalid.')
    value={'version':tag,'old_version':VERSION,'url':asset['browser_download_url'],'bytes':asset['size'],'sha256':sha,'release_url':f'https://github.com/{REPO}/releases/tag/v{tag}','notes':(release.get('body') or '')[:4000]}
    key=uid();db.execute('INSERT INTO app_update_quotes VALUES(?,?,?,?)',(key,session['hash'],encode(value),now()+1800))
    return {'quote_id':key,'installed':VERSION,'available':True,**value}

class Review(BaseModel):
    model_config=ConfigDict(extra='forbid')
    quote_id:str
class Confirm(BaseModel):
    model_config=ConfigDict(extra='forbid')
    confirm:bool=False

@router.post('/stage')
async def stage(body:Review,session=Depends(require_session)):
    migrate();previous=read_plan()
    if previous and previous['state'] in {'applying','checking','rolling_back','scheduled','rollback_scheduled'}:raise ValueError('Recover the current update before preparing another.')
    row=db.one('SELECT body FROM app_update_quotes WHERE id=? AND session=? AND expires>?',(body.quote_id,session['hash'],now()))
    if not row:raise ValueError('Check for updates again to review its current package.')
    review=json.loads(row['body']);identifier=uid();folder=storage.role_folder('cache')/('app-update-'+identifier)
    storage.reject_links(folder);folder.mkdir(parents=True,exist_ok=True);storage.require_space(folder,review['bytes']*4);storage.require_space(ROOT,review['bytes']*2)
    raw=await fetch(review['url'],review['bytes'],review['bytes'])
    if raw is None:raise ValueError('This update package was removed. Check for updates again.')
    archive=folder/'application.zip';archive.write_bytes(raw)
    if digest(archive)!=review['sha256']:raise ValueError('The update checksum did not match. The installed app was not changed.')
    destination=folder/'application';value=await asyncio.to_thread(extract,archive,destination)
    if value['version']!=review['version']:raise ValueError('The package version did not match the reviewed release.')
    if digest(destination/'backend/bootstrap-lock.txt')!=digest(ROOT/'backend/bootstrap-lock.txt'):raise ValueError('This release changes program dependencies. Its Windows setup requires a separate review; the installed app is preserved.')
    backup=storage.role_folder('backups')/'app-updates'/identifier;storage.reject_links(backup)
    plan={'schema':1,'id':identifier,'root':str(ROOT),'session':session['hash'],'state':'prepared','stage':str(destination),'backup':str(backup),'manifest_sha256':digest(destination/'release-manifest.json'),**{k:review[k] for k in ['version','old_version','release_url']}}
    write_plan(plan)
    return {'prepared':True,'version':review['version'],'files':len(value['files']),'message':'Update verified and prepared. Finish any work, then choose Update and reopen Studio.'}

async def stop_self():
    await asyncio.sleep(.6);psutil.Process(os.getpid()).terminate()

def dispatch(plan,rollback=False):
    idle();process=psutil.Process()
    if not any(Path(arg).resolve()==(ROOT/'backend/run.py').resolve() for arg in process.cmdline() if str(arg).endswith('run.py')):raise ValueError('Open this installation with START_STUDIO before applying an update.')
    plan['parent']={'pid':process.pid,'created':process.create_time()};plan['state']='rollback_scheduled' if rollback else 'scheduled';write_plan(plan)
    log=ROOT/'logs'/'app-update.log'
    with log.open('ab') as out:
        subprocess.Popen([sys.executable,str(ROOT/'backend/apply_update.py'),'--root',str(ROOT),*(['--rollback'] if rollback else [])],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=out,stderr=subprocess.STDOUT,creationflags=0x08000000 if os.name=='nt' else 0)

@router.post('/apply')
async def apply(body:Confirm,background_tasks:BackgroundTasks,session=Depends(require_session)):
    plan=read_plan()
    if not body.confirm or not plan or plan['state']!='prepared' or plan['session']!=session['hash']:raise ValueError('Prepare and review this update in the same browser before applying it.')
    validate(Path(plan['stage']));dispatch(plan);background_tasks.add_task(stop_self)
    return {'restarting':True,'message':'Studio is updating and will reopen locally. Saved productions and models stay in place.'}

@router.post('/rollback')
async def restore(body:Confirm,background_tasks:BackgroundTasks,session=Depends(require_session)):
    plan=read_plan()
    if not body.confirm or not plan or plan['state']!='applied':raise ValueError('Review an applied update before restoring its earlier application files.')
    for item in plan.get('journal',[]):
        expected=next(f for f in validate(Path(plan['stage']))['files'] if f['path']==item['path'])
        if digest(ROOT/item['path'])!=expected['sha256']:raise ValueError('Application source changed after this update. Keep those edits and review the backup manually before restoring.')
    dispatch(plan,True);background_tasks.add_task(stop_self)
    return {'restarting':True,'message':'Restoring the previous application files. Production data and models are kept.'}
