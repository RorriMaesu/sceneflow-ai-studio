import os
import sys
import logging
import json
import re
from datetime import datetime,timezone
from pathlib import Path

import uvicorn

os.environ.setdefault('STUDIO_ROOT', str(Path(__file__).resolve().parents[1]))
from studio.config import PORT, ROOT, private

if __name__ == '__main__':
    class JsonLog(logging.Formatter):
        def format(self,record):
            message=super().format(record)
            message=re.sub(r'([?&](?:ticket|token|code)=)[^&\s\"]+',r'\1[redacted]',message)
            return json.dumps({'time':datetime.now(timezone.utc).isoformat(),'level':record.levelname,'logger':record.name,'message':message})
    handler=logging.StreamHandler()
    handler.setFormatter(JsonLog())
    logging.basicConfig(level=logging.INFO,handlers=[handler],force=True)
    lock=(ROOT/'database'/'agent.lock').open('a+b')
    try:
        if os.name=='nt':
            import msvcrt
            lock.seek(0)
            if not lock.read(1):
                lock.write(b'0');lock.flush()
            lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        print('SceneFlow is already running at http://127.0.0.1:'+str(PORT),flush=True)
        sys.exit(0)
    (ROOT/'config'/'agent.pid').write_text(str(os.getpid()))
    print(f'SceneFlow Studio · http://127.0.0.1:{PORT}', flush=True)
    print(f'Pairing code: {private["pair_code"]} (expires in ten minutes)', flush=True)
    uvicorn.run('studio.app:app', host='127.0.0.1', port=PORT, workers=1, access_log=False, log_level='info',log_config=None)
