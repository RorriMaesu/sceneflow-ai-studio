import os
from pathlib import Path

import uvicorn

os.environ.setdefault('STUDIO_ROOT', str(Path(__file__).resolve().parents[1]))
from studio.config import PORT, ROOT, private

if __name__ == '__main__':
    print(f'SceneFlow Studio · http://127.0.0.1:{PORT}', flush=True)
    print(f'Pairing code: {private["pair_code"]} (expires in ten minutes)', flush=True)
    uvicorn.run('studio.app:app', host='127.0.0.1', port=PORT, workers=1, access_log=False, log_level='info')
