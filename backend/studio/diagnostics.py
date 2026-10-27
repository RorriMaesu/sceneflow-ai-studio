from .adapters import registry
from .config import PHASE,VERSION
from .media import asset_path,executable
from .resources import resources,services
from .store import db


async def diagnostics():
    tools={}
    for kind in ['ffmpeg','ffprobe']:
        try:executable(kind);tools[kind]='available'
        except ValueError:tools[kind]='missing'
    missing=[]
    for asset in db.all('SELECT id,project_id FROM assets'):
        try:asset_path(asset['id'])
        except (FileNotFoundError,ValueError):missing.append({'asset_id':asset['id'],'project_id':asset['project_id']})
    return {'version':VERSION,'phase':PHASE,'privacy':'No prompts, conversations, pairing codes, session tokens, or raw logs are included.','services':await services(True),'resources':resources(),'media_tools':tools,'workflows':[{'id':w['id'],'name':w['name'],'status':w['status'],'generation_verified':w.get('tested',False),'reasons':w['reasons']} for w in registry.list()],'projects':len(db.projects()),'jobs_by_status':db.all('SELECT status,COUNT(*) count FROM jobs GROUP BY status'),'missing_assets':missing,'limits':['Vision scores are advisory; sampled video frames do not prove complete motion adherence.','Unconfigured LTX audio, outpainting and neural upscaling workflows remain unavailable.']}
