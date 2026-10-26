"""One-click Windows startup; only process-local environment changes."""
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path
from urllib.parse import quote

root=Path(__file__).resolve().parents[1]
os.environ['STUDIO_ROOT']=str(root)
os.environ.update(TEMP=str(root/'temp'),TMP=str(root/'temp'),PYTHONIOENCODING='utf-8')
from studio.config import PORT,VERSION,rotate_pair_code,settings


def get(url):
    try:
        with urllib.request.urlopen(url,timeout=2) as response:return json.load(response)
    except Exception:return None


def start(arguments,name,environment=None):
    logs=root/'logs';logs.mkdir(exist_ok=True)
    with (logs/(name+'_stdout.log')).open('a',encoding='utf-8') as output,(logs/(name+'_stderr.log')).open('a',encoding='utf-8') as error:
        return subprocess.Popen(arguments,cwd=root,env=environment or os.environ.copy(),stdin=subprocess.DEVNULL,stdout=output,stderr=error,creationflags=0x08000000 if os.name=='nt' else 0)


def stop_owned_agent():
    import psutil
    path=root/'config'/'agent.pid'
    if not path.exists():return False
    try:
        process=psutil.Process(int(path.read_text()))
        command=process.cmdline()
        expected=str((root/'backend'/'run.py').resolve()).casefold()
        if not any(str(Path(arg).resolve()).casefold()==expected for arg in command[1:] if arg.endswith('run.py')):return False
        process.terminate();process.wait(timeout=10);return True
    except (psutil.NoSuchProcess,ValueError):return True


def main():
    address=f'http://127.0.0.1:{PORT}'
    if '--stop' in sys.argv:
        print('Studio Agent stopped; saved jobs can recover on the next launch.' if stop_owned_agent() else 'No owned Studio Agent was found.');return
    current=get(address+'/api/health')
    if current and current.get('service')!='SceneFlow Studio Agent':raise RuntimeError('Another service occupies the Studio port.')
    if current and current.get('version')!=VERSION:
        if not stop_owned_agent():raise RuntimeError('An older agent is running outside this installation. Close it before opening this version.')
        current=None
    comfy=Path(settings.get('comfy_launcher','M:/ComfyUI/run_nvidia_gpu.bat'))
    if settings.get('auto_start_comfy',True) and not get(settings['comfy_url']+'/system_stats') and comfy.is_file():
        start(['cmd.exe','/d','/c',str(comfy)],'comfy_launcher')
    ollama=shutil.which('ollama') or str(Path(os.environ.get('LOCALAPPDATA',''))/'Programs'/'Ollama'/'ollama.exe')
    if settings.get('auto_start_ollama',True) and not get(settings['ollama_url']+'/api/tags') and Path(ollama).is_file():
        model_root=Path(settings.get('ollama_models','M:/AiStudio/OllamaModels'))
        if not model_root.exists():model_root=root/'models'/'ollama';model_root.mkdir(parents=True,exist_ok=True)
        env={**os.environ,'OLLAMA_HOST':'127.0.0.1:11434','OLLAMA_MODELS':str(model_root),'OLLAMA_ORIGINS':address,'OLLAMA_KEEP_ALIVE':'5m','OLLAMA_NO_CLOUD':'1'}
        start([ollama,'serve'],'ollama_launcher',env)
    code=rotate_pair_code()
    if not current:start([str(root/'.venv'/'Scripts'/'python.exe'),str(root/'backend'/'run.py')],'agent_launcher')
    for _ in range(30):
        if get(address+'/api/health'):break
        time.sleep(1)
    else:raise RuntimeError('Studio did not start. See the local agent launcher log.')
    print('SceneFlow is ready at '+address)
    if '--quiet' not in sys.argv:print('One-use pairing code: '+code+' (10 minutes)')
    print('The browser can close while production continues. Use STOP_STUDIO.bat to stop only this agent.')
    if '--no-browser' not in sys.argv:webbrowser.open(address+'/#pair='+quote(code))


if __name__=='__main__':
    try:main()
    except Exception as error:
        print('Startup could not finish: '+str(error));sys.exit(1)
