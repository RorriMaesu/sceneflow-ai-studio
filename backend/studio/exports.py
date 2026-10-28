import copy
import json
import math
from pathlib import Path

from .config import ROOT
from .media import add_asset, asset_path, executable, probe, run_tool
from .store import Conflict, db, encode, now, uid


def rebuild_timeline(project_id,partial=False):
    project=db.project(project_id)
    clips=[]
    for scene in project['scenes']:
        if scene['body'].get('disabled'):
            continue
        if not scene['selected_video_id']:
            if partial:
                continue
            raise ValueError('Select a valid video take for every included scene before building the timeline.')
        asset=db.one('SELECT * FROM assets WHERE id=? AND scene_id=? AND kind=?',(scene['selected_video_id'],scene['id'],'video'))
        if not asset:
            raise ValueError('A selected take no longer belongs to its scene.')
        metadata=json.loads(asset['metadata'])
        clips.append({'id':uid(),'scene_id':scene['id'],'asset_id':asset['id'],'trim_in':0,'trim_out':metadata['duration'],'speed':1,'volume':1,'mute':False,'transition':'inherit'})
        if not metadata.get('audio_streams') and asset['job_id']:
            audio=db.one("SELECT id FROM assets WHERE job_id=? AND scene_id=? AND kind='audio' ORDER BY created LIMIT 1",(asset['job_id'],scene['id']))
            if audio:clips[-1]['audio_asset_id']=audio['id']
    timeline=project['timeline']
    return save_timeline(project_id,timeline['revision'],clips,timeline.get('audio',[]),{**timeline['settings'],'partial':len(clips)<sum(not s['body'].get('disabled') for s in project['scenes'])},automatic=True)


def save_timeline(project_id,revision,clips,audio,settings,automatic=False):
    if not 0 < len(clips) <= 200:
        raise ValueError('A timeline needs between one and 200 clips.')
    if len({c.get('id') for c in clips})!=len(clips) or any(not isinstance(c.get('id'),str) for c in clips):
        raise ValueError('Each timeline clip needs its own unique ID.')
    for clip in clips:
        asset=db.one('SELECT * FROM assets WHERE id=? AND project_id=? AND kind IN (?,?)',(clip.get('asset_id'),project_id,'video','image'))
        if not asset or asset['scene_id']!=clip.get('scene_id'):
            raise ValueError('A timeline clip must reference media from its own scene and project.')
        metadata=json.loads(asset['metadata'])
        duration=float(metadata.get('duration',clip.get('duration',5)))
        start=float(clip.get('trim_in',0));end=float(clip.get('trim_out',duration));speed=float(clip.get('speed',1))
        if not all(math.isfinite(v) for v in [start,end,speed]) or not 0<=start<end<=min(duration+.1,3600) or not .25<=speed<=4:
            raise ValueError('Clip trims or playback speed are outside the source duration.')
        if clip.get('transition','inherit') not in ['inherit','cut','fade','fade_black','dissolve'] or not math.isfinite(float(clip.get('volume',1))) or not 0<=float(clip.get('volume',1))<=4:
            raise ValueError('Invalid clip transition or volume.')
        if clip.get('audio_asset_id') and not db.one("SELECT id FROM assets WHERE id=? AND project_id=? AND scene_id=? AND kind='audio' AND job_id=?",(clip['audio_asset_id'],project_id,clip['scene_id'],asset['job_id'])):
            raise ValueError('A generated audio sidecar must share the clip’s exact scene and job.')
    if len(audio)>200:
        raise ValueError('Use at most 200 audio tracks per sequence. Split longer scripts into more sequences.')
    for track in audio:
        asset=db.one('SELECT * FROM assets WHERE id=? AND project_id=? AND kind=?',(track.get('asset_id'),project_id,'audio'))
        if not asset:
            raise ValueError('An audio track must belong to this project.')
        duration=json.loads(asset['metadata'])['duration']
        track.setdefault('trim_out',duration)
        start=float(track.get('trim_in',0));end=float(track['trim_out'])
        numbers=[start,end,float(track.get('start',0)),float(track.get('volume',1)),float(track.get('fade_in',0)),float(track.get('fade_out',0))]
        if not all(math.isfinite(v) for v in numbers) or not 0<=start<end<=duration+.1 or not 0<=numbers[2]<=36000 or not 0<=numbers[3]<=4 or not 0<=min(numbers[4:])<=max(numbers[4:])<=3600 or track.get('role','music') not in ['music','voiceover','effects']:
            raise ValueError('Audio trim, placement, volume, fade or role is invalid.')
    width=int(settings.get('width',1920));height=int(settings.get('height',1080));fps=int(settings.get('fps',30))
    if not 64<=width<=3840 or not 64<=height<=2160 or width%2 or height%2 or not 1<=fps<=60:
        raise ValueError('Choose an even export size up to 3840×2160 and a frame rate from 1 to 60.')
    if settings.get('fit','pad') not in ['pad','crop'] or settings.get('audio_mode','silent') not in ['silent','preserve','mixed']:
        raise ValueError('Invalid export fitting or audio policy.')
    if not 1<=int(settings.get('repeats',1))<=20:
        raise ValueError('Use between one and twenty loop repetitions.')
    if settings.get('loop','none') not in ['none','continuous','fade_black','crossfade'] or settings.get('transition','cut') not in ['cut','fade','fade_black','dissolve'] or settings.get('codec','h264') not in ['h264','h265'] or not 0<=int(settings.get('crf',18))<=40 or not .05<=float(settings.get('transition_duration',.35))<=2:
        raise ValueError('Export codec, quality, transition, or loop setting is invalid.')
    body={'clips':clips,'audio':audio,'settings':settings}
    with db.connect(True) as con:
        row=con.execute('SELECT revision FROM timelines WHERE project_id=?',(project_id,)).fetchone()
        if not row or row['revision']!=revision:
            raise Conflict('The timeline changed in another view. Refresh before saving.')
        con.execute('CREATE TABLE IF NOT EXISTS timeline_revisions(project_id TEXT,revision INTEGER,body TEXT,created REAL,PRIMARY KEY(project_id,revision))')
        previous=con.execute('SELECT body FROM timelines WHERE project_id=?',(project_id,)).fetchone()
        old=json.loads(previous['body'])
        body['settings']={**settings,'manual_edit':False if automatic else bool(old['settings'].get('manual_edit') or old['clips']!=clips)}
        con.execute('INSERT OR IGNORE INTO timeline_revisions VALUES(?,?,?,?)',(project_id,revision,previous['body'],now()))
        con.execute('INSERT INTO timeline_revisions VALUES(?,?,?,?)',(project_id,revision+1,encode(body),now()))
        con.execute('UPDATE timelines SET revision=revision+1,body=?,updated=? WHERE project_id=?',(encode(body),now(),project_id))
    db.event('timeline.updated',{'project_id':project_id,'revision':revision+1})
    return {**body,'revision':revision+1}


def queue_export(project_id,automatic=False,preview=False):
    from .production import pause,queue_snapshot
    project=db.project(project_id)
    timeline=copy.deepcopy(project['timeline'])
    if not timeline or not timeline['clips']:
        raise ValueError('Build and save a timeline before exporting.')
    frozen={'project_id':project_id,'scene_id':None,'title':project['title'],'timeline':timeline,'timeline_revision':timeline['revision']}
    from .music_planning import captions
    subtitles=captions(project_id,db)
    if subtitles['source'].get('include_mp4') and subtitles['items']:
        frozen.update(captions=subtitles['items'],caption_revision=subtitles['revision'])
    if preview:
        config=timeline['settings'];factor=min(1,640/max(config['width'],config['height']))
        timeline['settings']={**config,'width':max(64,int(config['width']*factor/2)*2),'height':max(64,int(config['height']*factor/2)*2),'fps':min(24,config['fps']),'codec':'h264','crf':28}
        frozen.update(title='Editing preview · '+project['title'],is_editing_preview=True)
    for clip in timeline['clips']+timeline.get('audio',[]):
        path=asset_path(clip['asset_id'])
        asset=db.one('SELECT sha256,project_id FROM assets WHERE id=?',(clip['asset_id'],))
        if asset['project_id']!=project_id:
            raise ValueError('Export assets must belong to this project.')
        clip['source_sha256']=asset['sha256']
        if clip.get('audio_asset_id'):
            audio=db.one("SELECT sha256 FROM assets WHERE id=? AND project_id=? AND kind='audio'",(clip['audio_asset_id'],project_id))
            if not audio:raise ValueError('The generated audio sidecar is missing.')
            clip['audio_source_sha256']=audio['sha256']
    return queue_snapshot('export',frozen,automatic=automatic)


def execute_export(job,snapshot):
    from .editing_export import execute
    return execute(job,snapshot)

