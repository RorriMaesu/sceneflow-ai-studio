"""Opt-in generic tray notices; no project text or credentials leave the agent."""
import json
import os

from .config import ROOT, settings
from .store import uid


def notice(kind, data):
    if not settings.get('desktop_notifications') or kind != 'job.updated' or data.get('status') not in ['completed','failed','needs_attention']:return
    label = {'image':'Still generation','video':'Animation','export':'Movie export','qa':'Quality review','ai':'Director'}.get(data.get('kind'),'Studio job')
    status = 'completed' if data['status'] == 'completed' else 'needs your attention'
    value = {'id':uid(), 'title':'SceneFlow', 'message':label+' '+status+'.'}
    path = ROOT/'logs'/'desktop-notice.json'; temporary = path.with_name('desktop-notice.'+uid()+'.tmp')
    try:
        temporary.write_text(json.dumps(value), encoding='utf-8'); os.replace(temporary,path)
    except OSError:
        temporary.unlink(missing_ok=True)
