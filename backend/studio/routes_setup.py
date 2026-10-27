import asyncio
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from . import model_library, storage
from .config import VERSION, settings, save_settings
from .resources import resources, services
from .security import require_session
from .store import db, now, uid, encode

router = APIRouter(prefix='/api/setup')


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Routes(Strict):
    routes: dict[str, str]


class Quote(Strict):
    root_id: str | None = None


class Install(Strict):
    quote_id: str
    confirm: bool = False


@router.get('')
async def readiness(session=Depends(require_session)):
    from .resource_broker import status as memory_status
    from .runtime_installer import jobs as runtime_jobs
    from .audio_engine import qualification
    folders = storage.status()
    local = await services(True)
    return {'version': VERSION, 'storage': folders, 'resources': resources(), 'services': local, 'memory_manager': memory_status(),
            'packs': model_library.list_packs(), 'downloads': model_library.downloads(),
            'runtime_jobs': runtime_jobs(), 'samples': {p: (qualification(p) or {}).get('body') for p in ['voices-small','music','effects']},
            'setup_complete': bool(settings.get('setup_complete')),
            'can_use_existing_tools': local['comfy']['connected'],
            'next_action': 'Choose where your files go.' if not folders['routes'] else 'Choose only the tools your production needs.'}


@router.post('/folders/recommended')
async def recommended(session=Depends(require_session)):
    return await asyncio.to_thread(storage.recommended)


@router.post('/folders/choose')
async def choose(session=Depends(require_session)):
    return {'root': await asyncio.to_thread(storage.choose_folder)}


@router.post('/folders/routes')
async def routes(body: Routes, session=Depends(require_session)):
    return storage.use_routes(body.routes)


@router.post('/finish')
async def finish(session=Depends(require_session)):
    current = storage.status()
    if not current['routes'] or any(not r['available'] for r in current['roots'] if r['id'] in current['routes'].values()):
        raise ValueError('Choose available storage folders before finishing setup.')
    save_settings({'setup_complete': True})
    return {'complete': True, 'message': 'Your studio is set up. You can add voices, music or other tools whenever you need them.'}


@router.post('/packs/{identifier}/quote')
async def quote_pack(identifier: str, body: Quote, session=Depends(require_session)):
    return await asyncio.to_thread(model_library.quote_install, identifier, session, body.root_id)


@router.post('/downloads')
async def download(body: Install, session=Depends(require_session)):
    if not body.confirm:
        raise ValueError('Review and confirm the download size and folder first.')
    row = model_library.start_download(body.quote_id, session)
    return {k: v for k, v in row.items() if k != 'body'}


@router.post('/downloads/{identifier}/pause')
async def pause_download(identifier: str, session=Depends(require_session)):
    row = db.one('SELECT * FROM model_downloads WHERE id=?', (identifier,))
    if not row:
        raise KeyError('Download not found')
    if row['status'] in ('queued', 'downloading', 'verifying'):
        db.execute("UPDATE model_downloads SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'paused' ELSE status END WHERE id=?", (identifier,))
    return {'paused': True}


@router.post('/downloads/{identifier}/resume')
async def resume_download(identifier: str, session=Depends(require_session)):
    row = db.one('SELECT * FROM model_downloads WHERE id=?', (identifier,))
    if not row or row['status'] not in ('paused', 'failed'):
        raise ValueError('Choose a paused or failed download.')
    body = json.loads(row['body'])
    value = model_library.pack(row['pack_id'])
    if model_library.manifest_hash(value) != body['manifest_hash']:
        raise ValueError('This pack changed. Review a new download first.')
    body['session'] = session['hash']
    storage.require_space(model_library.install_path(value, row['root_id']), max(0, row['bytes_total'] - row['bytes_done']))
    db.execute("UPDATE model_downloads SET status='queued',cancel_requested=0,error=NULL,body=?,updated=? WHERE id=?", (json.dumps(body), now(), identifier))
    return {'resumed': True}


@router.post('/updates/check')
async def updates(session=Depends(require_session)):
    return await model_library.check_updates()


@router.post('/packs/{identifier}/runtime-quote')
async def runtime_quote(identifier:str,session=Depends(require_session)):
    from .runtime_installer import PACK_RUNTIME,quote,migrate
    if identifier not in PACK_RUNTIME:raise ValueError('This tool does not have an automatic program setup yet.')
    migrate()
    value=await asyncio.to_thread(quote,PACK_RUNTIME[identifier])
    value['id']=uid()
    db.execute('INSERT INTO runtime_quotes VALUES(?,?,?,?,0)',(value['id'],session['hash'],encode(value),now()+1800))
    return value


@router.post('/runtimes')
async def install_runtime(body:Install,session=Depends(require_session)):
    from .runtime_installer import queue,migrate,manifest
    migrate()
    with db.connect(True) as con:
        row=con.execute('SELECT * FROM runtime_quotes WHERE id=? AND session=? AND expires>? AND used=0',(body.quote_id,session['hash'],now())).fetchone()
        if not body.confirm or not row:raise ValueError('Review and confirm the program setup size and folder first.')
        value=json.loads(row['body'])
        if manifest(value['runtime_id'])['hash']!=value['manifest_hash']:raise ValueError('The setup recipe changed. Review setup again.')
        con.execute('UPDATE runtime_quotes SET used=1 WHERE id=?',(body.quote_id,))
    return queue(value['runtime_id'],value['root_id'])


class Probe(Strict):
    seconds:float|None=Field(default=None,ge=1,le=60,allow_inf_nan=False)


@router.post('/packs/{identifier}/sample')
async def sample(identifier:str,body:Probe,session=Depends(require_session)):
    from .audio_engine import queue_probe
    return await asyncio.to_thread(queue_probe,identifier,body.seconds)
