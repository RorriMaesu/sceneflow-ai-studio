import json
import os
import secrets
import time
from pathlib import Path

VERSION = '0.8.0'
PHASE = 'Phase 8 · Keyframes & studio care'
ROOT = Path(os.environ.get('STUDIO_ROOT', Path(__file__).resolve().parents[2])).resolve()
PORT = int(os.environ.get('STUDIO_PORT', '8770'))
for name in ['config', 'database', 'cache', 'temp', 'logs', 'projects', 'backups', 'workflows']:
    (ROOT / name).mkdir(parents=True, exist_ok=True)
DEFAULTS = {
    'comfy_url': 'http://127.0.0.1:8188', 'ollama_url': 'http://127.0.0.1:11434',
    'comfy_root': 'M:/ComfyUI/ComfyUI', 'ffmpeg': '', 'ffprobe': '',
    'vram_reserve_mb': 1800, 'memory_profile': 'conservative', 'disk_reserve_gb': 5,
    'pages_url': 'https://rorrimaesu.github.io/sceneflow-ai-studio/',
    'desktop_notifications': False,
}
SETTINGS_FILE = ROOT / 'config' / 'settings.json'
settings = {**DEFAULTS, **(json.loads(SETTINGS_FILE.read_text()) if SETTINGS_FILE.exists() else {})}
ALLOWED_ORIGINS = {f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}', 'http://127.0.0.1:5173', 'http://localhost:5173', 'https://rorrimaesu.github.io'}
SECRET_FILE = ROOT / 'config' / 'agent.json'
if SECRET_FILE.exists():
    private = json.loads(SECRET_FILE.read_text())
else:
    private = {'secret': secrets.token_hex(32), 'pair_code': '', 'pair_expires': 0}


def rotate_pair_code():
    private.update(pair_code=secrets.token_urlsafe(9), pair_expires=time.time() + 600)
    temporary=SECRET_FILE.with_name(SECRET_FILE.name+'.'+secrets.token_hex(4)+'.tmp')
    temporary.write_text(json.dumps(private, indent=2), encoding='utf-8')
    os.replace(temporary,SECRET_FILE)
    return private['pair_code']


def save_settings(values):
    settings.update(values)
    SETTINGS_FILE.write_text(json.dumps(settings, indent=2), encoding='utf-8')


if not private['pair_code'] or private['pair_expires'] < time.time():
    rotate_pair_code()
