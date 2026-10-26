import hashlib
import hmac
import secrets
import time
import json
from collections import defaultdict

from fastapi import HTTPException, Request

from .config import ALLOWED_ORIGINS, PORT, SECRET_FILE,private, rotate_pair_code
from .store import db, now

failures = defaultdict(list)
tickets = {}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def check_origin(origin):
    if origin is not None and origin not in ALLOWED_ORIGINS:
        raise HTTPException(403, 'This website is not paired with the local studio.')


def require_session(request: Request):
    check_origin(request.headers.get('origin'))
    authorization = request.headers.get('authorization', '')
    if not authorization.startswith('Bearer '):
        raise HTTPException(401, 'Connect to your local Studio Agent first.')
    row = db.one('SELECT * FROM sessions WHERE hash=?', (digest(authorization[7:]),))
    if not row or row['expires'] < now():
        raise HTTPException(401, 'Your connection expired. Pair with the Studio Agent again.')
    origin = request.headers.get('origin')
    if origin is not None and origin != row['origin']:
        raise HTTPException(403, 'This session belongs to a different browser origin.')
    return row


def pair(code, origin, label, client):
    check_origin(origin)
    # The local launcher can rotate the one-use code while an existing agent runs.
    if SECRET_FILE.exists():
        current=json.loads(SECRET_FILE.read_text(encoding='utf-8'))
        private.update(pair_code=current['pair_code'],pair_expires=current['pair_expires'])
    recent = [t for t in failures[client] if t > now()-60]
    failures[client] = recent
    if len(recent) >= 5:
        raise HTTPException(429, 'Too many pairing attempts. Wait one minute and try again.')
    if private['pair_expires'] < now() or not hmac.compare_digest(code, private['pair_code']):
        failures[client].append(now())
        raise HTTPException(401, 'That pairing code is invalid or expired. Open the local launcher for a new code.')
    token = secrets.token_urlsafe(32)
    db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)', (digest(token), origin, label, now()+7*86400, now()))
    rotate_pair_code()
    return {'token': token, 'expires_in': 7*86400}


def ticket(session, purpose, resource='', ttl=90):
    value = secrets.token_urlsafe(24)
    tickets[value] = {'session': session['hash'], 'origin': session['origin'], 'purpose': purpose, 'resource': resource, 'expires': now()+ttl}
    for key in list(tickets):
        if tickets[key]['expires'] < now():
            tickets.pop(key, None)
    return value


def verify_ticket(value, purpose, resource='', origin=None, consume=False):
    data = tickets.get(value)
    if not data or data['expires'] < now() or data['purpose'] != purpose or data['resource'] != resource:
        raise HTTPException(401, 'Media access expired. Refresh the preview.')
    session = db.one('SELECT * FROM sessions WHERE hash=? AND expires>?', (data['session'], now()))
    if not session or (origin is not None and origin != data['origin']):
        raise HTTPException(403, 'This media connection is not authorized.')
    if consume:
        tickets.pop(value, None)
    return data
