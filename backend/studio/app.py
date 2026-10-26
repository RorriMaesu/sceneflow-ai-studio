import asyncio
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ALLOWED_ORIGINS, PHASE, PORT, ROOT, VERSION, rotate_pair_code, save_settings, settings
from .resources import resources, services
from .security import check_origin, pair, require_session, ticket, verify_ticket
from .store import Conflict, db
from .validation import project_settings,scene_body

log = logging.getLogger('studio')


@asynccontextmanager
async def lifespan(app):
    from .production import dispatcher
    await dispatcher.start()
    try:
        yield
    finally:
        await dispatcher.stop()


app = FastAPI(title='SceneFlow Studio Agent', version=VERSION, lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost'])
app.add_middleware(CORSMiddleware, allow_origins=sorted(ALLOWED_ORIGINS), allow_credentials=False, allow_methods=['GET', 'POST', 'PATCH', 'DELETE', 'OPTIONS'], allow_headers=['Authorization', 'Content-Type', 'Idempotency-Key'], expose_headers=['Content-Length', 'Content-Range', 'Accept-Ranges'])


@app.middleware('http')
async def guard(request, call_next):
    try:
        check_origin(request.headers.get('origin'))
    except HTTPException as error:
        return JSONResponse({'detail': error.detail}, status_code=error.status_code)
    if request.headers.get('content-type','').startswith('application/json') and int(request.headers.get('content-length') or 0)>3*1024**2:
        return JSONResponse({'detail':'This JSON request exceeds 3 MB.'},status_code=413)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store' if request.url.path.startswith('/api') else 'no-cache'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data: http://127.0.0.1:8770; media-src 'self' blob: http://127.0.0.1:8770; connect-src 'self' http://127.0.0.1:8770 ws://127.0.0.1:8770; object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    return response


@app.exception_handler(Conflict)
async def conflict_handler(request, error):
    return JSONResponse({'detail': str(error)}, status_code=409)


@app.exception_handler(KeyError)
async def missing_handler(request, error):
    return JSONResponse({'detail': str(error).strip("'")}, status_code=404)


@app.exception_handler(ValueError)
async def validation_handler(request,error):
    return JSONResponse({'detail':str(error)},status_code=422)


@app.exception_handler(FileNotFoundError)
async def missing_file_handler(request,error):
    return JSONResponse({'detail':'This project media file is missing. Restore a backup or import a replacement.'},status_code=404)


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')


class PairInput(Strict):
    code: str = Field(min_length=4, max_length=100)
    label: str = Field(default='Studio browser', max_length=100)


class ProjectInput(Strict):
    title: str = Field(min_length=1, max_length=160)
    brief: str = Field(default='', max_length=30000)
    mode: str = Field(default='hybrid', pattern='^(manual|hybrid|automatic)$')
    settings: dict = Field(default_factory=dict)


class ProjectEdit(Strict):
    revision: int
    title: str | None = Field(default=None, min_length=1, max_length=160)
    brief: str | None = Field(default=None, max_length=30000)
    mode: str | None = Field(default=None, pattern='^(manual|hybrid|automatic)$')
    settings: dict | None = None


class SceneInput(Strict):
    title: str = Field(min_length=1, max_length=160)
    body: dict = Field(default_factory=dict)


class SceneEdit(Strict):
    revision: int
    title: str | None = Field(default=None, min_length=1, max_length=160)
    body: dict | None = None


@app.get('/api/health')
async def health():
    return {'service': 'SceneFlow Studio Agent', 'version': VERSION, 'phase': PHASE, 'pairing_required': True}


def validate_workflows(values):
    from .adapters import registry
    for field in ['image_workflow','video_workflow']:
        if values.get(field) and registry.get(values[field])['status']!='ready':
            raise ValueError('Choose an available workflow from the Model Library.')


@app.post('/api/pair')
async def pairing(body: PairInput, request: Request):
    return pair(body.code, request.headers.get('origin'), body.label, request.client.host)


@app.post('/api/session/revoke')
async def revoke(session=Depends(require_session)):
    db.execute('DELETE FROM sessions WHERE hash=?', (session['hash'],))
    return {'revoked': True}


@app.post('/api/session/pair-code')
async def new_pair_code(session=Depends(require_session)):
    return {'code': rotate_pair_code(), 'expires_in': 600}


@app.get('/api/bootstrap')
async def bootstrap(session=Depends(require_session)):
    return {'version': VERSION, 'phase': PHASE, 'projects': db.projects(), 'jobs': db.jobs(), 'assets': db.assets(), 'resources': resources(), 'services': await services(), 'settings': settings}


@app.get('/api/resources')
async def resource_status(session=Depends(require_session)):
    return resources()


@app.get('/api/diagnostics')
async def diagnostic_report(session=Depends(require_session)):
    from .diagnostics import diagnostics
    return await diagnostics()


@app.get('/api/services')
async def service_status(session=Depends(require_session)):
    return await services(True)


@app.get('/api/projects')
async def project_list(session=Depends(require_session)):
    return db.projects()


@app.post('/api/projects')
async def create_project(body: ProjectInput, session=Depends(require_session)):
    project_settings(body.settings)
    validate_workflows(body.settings)
    return db.create_project(**body.model_dump())


@app.get('/api/projects/{identifier}')
async def project(identifier: str, session=Depends(require_session)):
    from .production import current_source,current_video
    value=db.project(identifier)
    for scene in value['scenes']:
        scene['image_current']=bool(current_source(scene));scene['video_current']=bool(current_video(scene))
    return value


@app.patch('/api/projects/{identifier}')
async def edit_project(identifier: str, body: ProjectEdit, session=Depends(require_session)):
    if body.settings:
        project_settings(body.settings)
        validate_workflows(body.settings)
        merged={**db.project(identifier)['settings'],**body.settings}
        if merged.get('qa_enabled'):
            from .director import model_details,llm_models
            model=merged.get('qa_model')
            if not model:raise ValueError('Select a verified installed vision model or Auto before enabling AI quality control.')
            if model=='auto':
                if not any('vision' in m['capabilities'] and not m.get('remote_host') for m in await llm_models()):raise ValueError('No installed local vision model is available. Manual review remains available.')
            elif 'vision' not in (await model_details(model))['capabilities']:raise ValueError('This installed model does not advertise vision support.')
    result=db.update_project(identifier, body.revision, body.model_dump(exclude_none=True, exclude={'revision'}))
    if body.mode=='manual':
        from .production import pause
        pause(identifier,True)
    elif body.mode=='automatic':
        db.execute("UPDATE jobs SET status='queued',error=NULL WHERE project_id=? AND status='awaiting_review'",(identifier,))
    if body.settings:
        from .production import supersede_pending
        for scene in result['scenes']:supersede_pending(scene['id'])
    return result


@app.post('/api/projects/{identifier}/scenes')
async def add_scene(identifier: str, body: SceneInput, session=Depends(require_session)):
    scene_body(body.body)
    validate_workflows(body.body)
    return db.add_scene(identifier, body.title, body.body)


@app.patch('/api/scenes/{identifier}')
async def edit_scene(identifier: str, body: SceneEdit, session=Depends(require_session)):
    scene_body(body.body)
    validate_workflows(body.body or {})
    result=db.update_scene(identifier, body.revision, body.title, body.body)
    from .production import supersede_pending
    supersede_pending(identifier)
    return result


@app.get('/api/scenes/{identifier}/revisions')
async def scene_revisions(identifier: str, session=Depends(require_session)):
    return db.all('SELECT * FROM scene_revisions WHERE scene_id=? ORDER BY number DESC', (identifier,))


@app.post('/api/projects/{identifier}/archive')
async def archive_project(identifier: str, session=Depends(require_session)):
    db.project(identifier)
    db.execute('UPDATE projects SET archived=1 WHERE id=?', (identifier,))
    return {'archived': True}


@app.get('/api/jobs')
async def jobs(project_id: str | None = None, session=Depends(require_session)):
    return db.jobs(project_id)


@app.get('/api/assets')
async def assets(project_id: str | None = None, session=Depends(require_session)):
    return db.assets(project_id=project_id)


@app.patch('/api/settings')
async def update_settings(values: dict, session=Depends(require_session)):
    if any(key not in settings for key in values):
        raise HTTPException(422, 'Unknown setting.')
    if set(values)-{'comfy_url','ollama_url','vram_reserve_mb','disk_reserve_gb','memory_profile'}:
        raise HTTPException(422,'Executable and storage paths are controlled by the local installation configuration.')
    for key,low,high in [('vram_reserve_mb',512,8192),('disk_reserve_gb',1,500)]:
        if key in values and (not isinstance(values[key],(int,float)) or not low<=values[key]<=high):raise ValueError('Resource reserves are outside supported bounds.')
    if 'memory_profile' in values and values['memory_profile'] not in ['conservative','balanced','performance']:raise ValueError('Unknown resource profile.')
    for key in ['comfy_url', 'ollama_url']:
        if key in values:
            parsed = urlparse(values[key])
            if parsed.scheme != 'http' or parsed.hostname not in ['127.0.0.1', 'localhost'] or parsed.username or parsed.password or parsed.path not in ['', '/'] or parsed.query or parsed.fragment:
                raise HTTPException(422, 'AI service addresses must point to this computer over loopback HTTP.')
            values[key] = values[key].rstrip('/')
    save_settings(values)
    return settings


@app.post('/api/events/ticket')
async def events_ticket(session=Depends(require_session)):
    return {'ticket': ticket(session, 'events')}


@app.websocket('/ws')
async def websocket(websocket: WebSocket):
    try:
        check_origin(websocket.headers.get('origin'))
        authorization=verify_ticket(websocket.query_params.get('ticket', ''), 'events', origin=websocket.headers.get('origin'), consume=True)
    except HTTPException:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    cursor = int(websocket.query_params.get('after', '0'))
    try:
        while True:
            from .store import now
            if not db.one('SELECT hash FROM sessions WHERE hash=? AND expires>?',(authorization['session'],now())):
                await websocket.close(code=1008)
                return
            rows = db.all('SELECT * FROM events WHERE id>? ORDER BY id LIMIT 100', (cursor,))
            for row in rows:
                row['data'] = json.loads(row['data'])
                await websocket.send_json(row)
                cursor = row['id']
            await websocket.send_json({'kind': 'heartbeat', 'cursor': cursor})
            await asyncio.sleep(2)
    except (WebSocketDisconnect, RuntimeError):
        return


from .routes_production import router as production_router
app.include_router(production_router)
from .routes_director import router as director_router
app.include_router(director_router)
from .routes_editing import router as editing_router
app.include_router(editing_router)


@app.get('/{path:path}')
async def frontend(path: str):
    if path.startswith(('api/', 'ws')):
        raise HTTPException(404, 'Operation not found.')
    root = (ROOT / 'frontend' / 'dist').resolve()
    target = (root / path).resolve()
    if not target.is_relative_to(root):
        raise HTTPException(403, 'Invalid application path.')
    if target.is_file():
        return FileResponse(target)
    if (root / 'index.html').exists():
        return FileResponse(root / 'index.html')
    return JSONResponse({'detail': 'The frontend has not been built. Run the setup script.'}, status_code=503)
