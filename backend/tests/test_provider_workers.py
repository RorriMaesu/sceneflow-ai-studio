import asyncio
import json
import subprocess
import sys
from pathlib import Path

import psutil
import pytest

from .test_foundation import connected
from studio import provider_workers as workers, storage
from studio.store import encode, now


def test_runtime_path_must_belong_to_the_registered_provider(connected, tmp_path):
    _, _, db = connected
    workers.migrate()
    folder = tmp_path / 'tools'
    folder.mkdir()
    root = storage.grant(folder)
    db.execute('INSERT INTO provider_runtimes VALUES(?,?,?,?,?,?)', ('voices-small', root['id'], 'outside/python.exe', 'ready', '{}', now()))
    with pytest.raises(ValueError, match='outside'):
        workers.runtime_python('voices-small')
    with pytest.raises(ValueError, match='setup'):
        workers.runtime_python('unknown-provider')


def test_only_the_exact_owned_worker_can_be_stopped(tmp_path):
    request = tmp_path / 'input.json'
    request.write_text(json.dumps({'job_id': 'owned', 'nonce': 'matching-nonce'}))
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', str(request)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    owner = psutil.Process(process.pid)
    row = {'job_id': 'owned', 'pid': process.pid, 'created': owner.create_time(), 'executable': owner.exe(), 'request_path': str(request), 'nonce': 'matching-nonce'}
    try:
        foreign = {**row, 'nonce': 'wrong-nonce'}
        assert workers.stop_owned(foreign) is False
        assert process.poll() is None
        assert workers.stop_owned(row) is True
        process.wait(timeout=5)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_reused_pid_never_grants_worker_ownership(tmp_path):
    process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    owner = psutil.Process(process.pid)
    try:
        row = {'job_id': 'old', 'pid': process.pid, 'created': owner.create_time() - 10, 'executable': owner.exe(), 'request_path': str(tmp_path / 'missing'), 'nonce': 'old'}
        assert workers.process_for(row) is None
        assert workers.stop_owned(row) is True
        assert process.poll() is None
    finally:
        process.kill()
        process.wait(timeout=5)


def test_a_provider_cannot_start_outside_the_shared_queue(connected):
    with pytest.raises(ValueError, match='shared graphics queue'):
        asyncio.run(workers.run({'id': 'not-admitted'}, 'voices-small', {}))
