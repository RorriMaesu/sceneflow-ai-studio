"""Single-GPU admission, ownership and measurements across provider processes."""
import asyncio
import ctypes
import json
import os
import time

import httpx
import psutil

from .config import ROOT, settings
from .resources import resources
from .store import db, encode, now

GIB = 1024 ** 3
GPU_KINDS = {'image', 'video', 'plan', 'director', 'qa', 'speech', 'music', 'effects', 'transcribe', 'align', 'lipsync', 'enhance'}
ACTIVE = {'running', 'submitted', 'reconciling'}


def migrate():
    with db.connect(True) as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS resource_reservations(resource TEXT PRIMARY KEY,job_id TEXT,owner_pid INTEGER,owner_created REAL,started REAL,updated REAL,body TEXT);
        CREATE TABLE IF NOT EXISTS resource_measurements(job_id TEXT PRIMARY KEY,body TEXT,updated REAL);
        ''')


class DeviceLock:
    """A named mutex survives Python exceptions and coordinates separate installations."""
    def __init__(self):
        self.handle = None

    def acquire(self):
        if self.handle is not None:
            return True
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
            kernel.CreateMutexW.restype = ctypes.c_void_p
            kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
            kernel.WaitForSingleObject.restype = ctypes.c_ulong
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            handle = kernel.CreateMutexW(None, False, 'Global\\SceneFlowGPU0')
            if not handle:
                return False
            result = kernel.WaitForSingleObject(handle, 0)
            if result not in (0, 0x80):
                kernel.CloseHandle(handle)
                return False
            self.handle = handle
        else:
            import fcntl
            from pathlib import Path
            handle = (Path('/tmp') / ('sceneflow-gpu0-' + str(os.getuid()) + '.lock')).open('a+')
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                return False
            self.handle = handle
        return True

    def release(self):
        if self.handle is None:
            return
        if os.name == 'nt':
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.ReleaseMutex(self.handle)
            kernel.CloseHandle(self.handle)
        else:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_UN)
            self.handle.close()
        self.handle = None


def alive(pid, created):
    try:
        return abs(psutil.Process(pid).create_time() - created) < .01
    except (psutil.Error, ValueError, TypeError):
        return False


def required(job):
    """Conservative admission floors; new providers also require a qualified profile."""
    snapshot = json.loads(job['snapshot']) if isinstance(job['snapshot'], str) else job['snapshot']
    kind = job['kind']
    if kind == 'video':
        scale = max(1, snapshot.get('width', 640) * snapshot.get('height', 352) * snapshot.get('frames', 49) / (640 * 352 * 49))
        return {'gpu_free': min(14 * GIB, (10 + scale) * GIB), 'ram_free': min(16 * GIB, (6 + 2 * scale) * GIB), 'basis': 'Conservative admission for the existing offloaded Wan preset; measured peaks are recorded per task.'}
    if kind == 'image':
        return {'gpu_free': 10 * GIB, 'ram_free': 6 * GIB, 'basis': 'Existing offloaded still workflow.'}
    if kind in {'plan', 'director', 'qa'}:
        return {'gpu_free': 9 * GIB, 'ram_free': 3 * GIB, 'basis': 'Bounded local planning/review. Provider checks the selected model separately.'}
    profile = snapshot.get('resource_profile')
    if not isinstance(profile, dict) or set(profile) - {'gpu_free', 'ram_free', 'basis'}:
        raise ValueError('This creation tool needs a measured setup profile before it can use the graphics card.')
    if any(not isinstance(profile.get(key), (int, float)) or profile[key] < 0 or profile[key] > 128 * GIB for key in ('gpu_free', 'ram_free')):
        raise ValueError('The resource profile is invalid. Run the tool setup test again.')
    return profile


def admission(profile, telemetry):
    gpu = telemetry.get('gpu')
    if not gpu:
        return 'Graphics memory could not be measured. Studio is waiting before loading another model.'
    reserve = max(2 * GIB, settings['vram_reserve_mb'] * 1024 ** 2)
    # Profiles express minimum free GPU including model/activation workspace; reserve stays outside it.
    if gpu['free'] < profile['gpu_free'] + reserve:
        return 'Waiting for enough graphics memory. Close another graphics-heavy app, or choose a lighter creation setting.'
    if telemetry.get('ram_available', 0) < profile['ram_free'] + GIB:
        return 'Waiting for enough computer memory. Close memory-heavy apps, or choose a lighter creation setting.'
    if telemetry.get('commit_limit') and telemetry['commit_limit'] - telemetry['commit_total'] < profile['ram_free'] + 2 * GIB:
        return 'Windows has too little memory headroom for this task. Your saved work is safe; free memory before continuing.'
    return None


class ResourceBroker:
    def __init__(self):
        self.lock = DeviceLock()
        self.job_id = None
        self.monitor = None
        self.measurement = None

    async def prepare_backend(self, job):
        """Only release cached Studio-owned Comfy weights after checking it is idle."""
        from .runtime_installer import busy_reason
        if reason := busy_reason():
            return reason
        from .provider_workers import active_reason
        reason = active_reason(job['id'])
        if reason:
            return reason
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            try:
                response = await client.get(settings['comfy_url'] + '/queue')
                response.raise_for_status()
                queue = response.json()
                if queue.get('queue_running') or queue.get('queue_pending'):
                    return 'Waiting for the current photo or video work to finish. Work started in another app is preserved.'
                history = await client.get(settings['comfy_url'] + '/history', params={'max_items': 1})
                if history.status_code == 200:
                    latest = next(iter(history.json().values()), {})
                    prompt = latest.get('prompt', [])
                    owner = prompt[3].get('sceneflow', {}).get('job_id') if len(prompt) > 3 and isinstance(prompt[3], dict) else None
                    original = db.one('SELECT status FROM jobs WHERE id=?', (owner,)) if owner else None
                    if original and original['status'] not in ACTIVE:
                        check = (await client.get(settings['comfy_url'] + '/queue')).json()
                        if not check.get('queue_running') and not check.get('queue_pending'):
                            response = await client.post(settings['comfy_url'] + '/free', json={'unload_models': True, 'free_memory': True})
                            response.raise_for_status()
            except (httpx.HTTPError, ValueError):
                if job['kind'] in {'image', 'video'}:
                    return 'The local photo/video service is unavailable. Start it and this task can continue.'
            try:
                response = await client.get(settings['ollama_url'] + '/api/ps')
                if response.status_code == 200 and response.json().get('models'):
                    return 'Waiting for an existing story-helper session to finish or unload. Other sessions are preserved.'
            except (httpx.HTTPError, ValueError):
                if job['kind'] in {'plan', 'director', 'qa'}:
                    return 'The local story helper is unavailable. Start it and this task can continue.'
        return None

    async def acquire(self, job, recovering=False):
        if job['kind'] not in GPU_KINDS:
            return None
        migrate()
        if self.job_id == job['id']:
            return None
        if self.job_id:
            return 'Another Studio task is still using the graphics card.'
        if not self.lock.acquire():
            return 'Another Studio window or process is using the graphics card. This task will wait.'
        process = psutil.Process()
        try:
            with db.connect(True) as con:
                held = con.execute('SELECT * FROM resource_reservations WHERE resource=?', ('gpu:0',)).fetchone()
                if held:
                    original = con.execute('SELECT status FROM jobs WHERE id=?', (held['job_id'],)).fetchone()
                    if alive(held['owner_pid'], held['owner_created']) or held['job_id'] != job['id'] and original and original['status'] in ACTIVE:
                        self.lock.release()
                        return 'Recovering the previous graphics task before starting another one.'
                con.execute('INSERT OR REPLACE INTO resource_reservations VALUES(?,?,?,?,?,?,?)', ('gpu:0', job['id'], process.pid, process.create_time(), now(), now(), '{}'))
            if not recovering:
                reason = await self.prepare_backend(job)
                if reason:
                    self.drop(job['id'])
                    return reason
                profile = required(job)
                reason = admission(profile, resources())
                if reason:
                    self.drop(job['id'])
                    return reason
            else:
                profile = {'basis': 'Recovery: no new model may start until the original backend task is reconciled.'}
            self.job_id = job['id']
            self.measurement = {'job_id': job['id'], 'kind': job['kind'], 'started': now(), 'profile': profile,
                                'gpu_used_peak': 0, 'ram_used_peak': 0, 'commit_used_peak': 0, 'samples': 0,
                                'note': 'Device-wide sampled peaks include other apps. They are observations, not guaranteed model maxima.'}
            self.sample()
            self.monitor = asyncio.create_task(self.watch())
            return None
        except BaseException:
            self.drop(job['id'])
            raise

    def sample(self):
        if not self.measurement:
            return
        telemetry = resources()
        values = self.measurement
        values['samples'] += 1
        values['gpu_used_peak'] = max(values['gpu_used_peak'], (telemetry.get('gpu') or {}).get('used', 0))
        values['ram_used_peak'] = max(values['ram_used_peak'], telemetry.get('ram_used', 0))
        values['commit_used_peak'] = max(values['commit_used_peak'], telemetry.get('commit_total') or 0)
        db.execute('UPDATE resource_reservations SET updated=?,body=? WHERE resource=? AND job_id=?', (now(), encode(values), 'gpu:0', self.job_id))
        db.execute('INSERT OR REPLACE INTO resource_measurements VALUES(?,?,?)', (self.job_id, encode(values), now()))

    async def watch(self):
        while True:
            await asyncio.sleep(1)
            try:
                self.sample()
            except Exception:
                # A monitoring write failure never permits an extra model load.
                pass

    def drop(self, identifier):
        try:
            db.execute('DELETE FROM resource_reservations WHERE resource=? AND job_id=?', ('gpu:0', identifier))
        finally:
            self.lock.release()

    async def release_if_terminal(self):
        if not self.job_id:
            return
        row = db.one('SELECT status FROM jobs WHERE id=?', (self.job_id,))
        if row and row['status'] in ACTIVE:
            return
        await self.release()

    async def release(self, stopping=False):
        if self.monitor:
            self.monitor.cancel()
            try:
                await self.monitor
            except asyncio.CancelledError:
                pass
            self.monitor = None
        if self.job_id:
            self.sample()
            if self.measurement:
                self.measurement['finished'] = now()
                db.execute('INSERT OR REPLACE INTO resource_measurements VALUES(?,?,?)', (self.job_id, encode(self.measurement), now()))
            # On shutdown preserve durable ownership of uncertain backend work for reconciliation.
            row = db.one('SELECT status FROM jobs WHERE id=?', (self.job_id,))
            if not stopping or not row or row['status'] not in ACTIVE:
                db.execute('DELETE FROM resource_reservations WHERE resource=? AND job_id=?', ('gpu:0', self.job_id))
        self.job_id = None
        self.measurement = None
        self.lock.release()


broker = ResourceBroker()


def status():
    migrate()
    row = db.one('SELECT * FROM resource_reservations WHERE resource=?', ('gpu:0',))
    return {'policy': 'One graphics-heavy task at a time', 'active': {k: v for k, v in row.items() if k not in {'owner_pid', 'owner_created'}} if row else None,
            'memory_unknown_policy': 'Wait before loading a model', 'external_apps': 'Preserved; never stopped automatically'}
