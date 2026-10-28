import asyncio
import json
import os
import subprocess
import sys

import httpx
import pytest

from .test_foundation import connected
from studio import resource_broker as rb
from studio.store import encode, now, uid


def telemetry():
    return {'gpu': {'free': 15 * rb.GIB, 'used': rb.GIB, 'total': 16 * rb.GIB},
            'ram_available': 20 * rb.GIB, 'ram_used': 10 * rb.GIB,
            'commit_limit': 64 * rb.GIB, 'commit_total': 20 * rb.GIB}


@pytest.fixture
def managed(connected, monkeypatch):
    _, _, db = connected
    rb.migrate()
    # Exercise the real OS mutex under a unique test name so running the test
    # suite cannot contend with a user's actual model job.
    actual_lock=rb.DeviceLock
    namespace='Local\\SceneFlow-test-'+uid()
    monkeypatch.setattr(rb,'DeviceLock',lambda:actual_lock(namespace))
    monkeypatch.setattr(rb, 'resources', telemetry)
    async def idle(self, job): return None
    monkeypatch.setattr(rb.ResourceBroker, 'prepare_backend', idle)
    project = db.create_project('Resource test')
    def task(kind='plan', status='queued', snapshot=None):
        identifier = uid()
        db.execute('INSERT INTO jobs(id,project_id,kind,status,snapshot,dependencies,created) VALUES(?,?,?,?,?,?,?)',
                   (identifier, project['id'], kind, status, encode(snapshot or {}), '[]', now()))
        return db.one('SELECT * FROM jobs WHERE id=?', (identifier,))
    return db, task


def test_named_device_lock_excludes_another_process():
    namespace='Local\\SceneFlow-test-'+uid()
    lock = rb.DeviceLock(namespace)
    assert lock.acquire()
    try:
        code = 'from studio.resource_broker import DeviceLock; value=DeviceLock('+repr(namespace)+'); print(value.acquire()); value.release()'
        output = subprocess.check_output([sys.executable, '-c', code], text=True, env=os.environ.copy(), timeout=20)
        assert output.strip() == 'False'
    finally:
        lock.release()


def test_another_broker_cannot_claim_the_same_or_different_job(managed):
    _, task = managed
    async def run():
        first, second = rb.ResourceBroker(), rb.ResourceBroker()
        a, b = task(), task()
        assert await first.acquire(a) is None
        try:
            assert await second.acquire(a)
            assert await second.acquire(b)
        finally:
            await first.release()
            await second.release()
    asyncio.run(run())


def test_unknown_vram_is_never_treated_as_free(managed, monkeypatch):
    db, task = managed
    monkeypatch.setattr(rb, 'resources', lambda: {**telemetry(), 'gpu': None})
    async def run():
        broker = rb.ResourceBroker()
        assert 'could not be measured' in await broker.acquire(task())
        assert not db.all('SELECT * FROM resource_reservations')
        assert broker.lock.handle is None
    asyncio.run(run())


@pytest.mark.parametrize('change, message', [
    ({'gpu': {'free': rb.GIB}}, 'graphics memory'),
    ({'ram_available': rb.GIB}, 'computer memory'),
    ({'commit_limit': 22 * rb.GIB}, 'headroom'),
])
def test_each_memory_budget_is_checked(managed, monkeypatch, change, message):
    _, task = managed
    monkeypatch.setattr(rb, 'resources', lambda: {**telemetry(), **change})
    async def run():
        broker = rb.ResourceBroker()
        assert message in await broker.acquire(task())
        assert broker.lock.handle is None
    asyncio.run(run())


def test_uncertain_backend_work_retains_the_reservation(managed):
    db, task = managed
    async def run():
        broker = rb.ResourceBroker()
        job = task(status='reconciling')
        assert await broker.acquire(job, recovering=True) is None
        await broker.release_if_terminal()
        assert broker.job_id == job['id'] and broker.lock.handle is not None
        db.execute("UPDATE jobs SET status='completed' WHERE id=?", (job['id'],))
        await broker.release_if_terminal()
        assert broker.job_id is None and not db.all('SELECT * FROM resource_reservations')
    asyncio.run(run())


def test_dead_owner_does_not_clear_an_unreconciled_different_job(managed):
    db, task = managed
    old, new = task(status='submitted'), task()
    db.execute('INSERT INTO resource_reservations VALUES(?,?,?,?,?,?,?)', ('gpu:0', old['id'], 99999999, 0, now(), now(), '{}'))
    async def run():
        broker = rb.ResourceBroker()
        assert 'Recovering' in await broker.acquire(new)
        assert await broker.acquire(old, recovering=True) is None
        db.execute("UPDATE jobs SET status='completed' WHERE id=?", (old['id'],))
        await broker.release_if_terminal()
    asyncio.run(run())


def test_peak_observations_are_recorded_with_their_limits(managed, monkeypatch):
    db, task = managed
    async def run():
        broker = rb.ResourceBroker()
        job = task()
        assert await broker.acquire(job) is None
        monkeypatch.setattr(rb, 'resources', lambda: {**telemetry(), 'gpu': {'used': 4 * rb.GIB, 'free': 12 * rb.GIB}})
        broker.sample()
        await broker.release()
        data = json.loads(db.one('SELECT body FROM resource_measurements WHERE job_id=?', (job['id'],))['body'])
        assert data['gpu_used_peak'] == 4 * rb.GIB and data['samples'] >= 2
        assert 'other apps' in data['note'] and data['finished'] >= data['started']
    asyncio.run(run())


def test_unqualified_new_provider_cannot_invent_its_memory_budget():
    with pytest.raises(ValueError, match='setup profile'):
        rb.required({'kind': 'music', 'snapshot': '{}'})
    with pytest.raises(ValueError, match='invalid'):
        rb.required({'kind': 'speech', 'snapshot': encode({'resource_profile': {'gpu_free': -1, 'ram_free': 0}})})
