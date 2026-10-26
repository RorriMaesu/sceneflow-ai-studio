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
        if not scene['selected_video_id']:
            if partial:
                continue
            raise ValueError('Select a valid video take for every included scene before building the timeline.')
        asset=db.one('SELECT * FROM assets WHERE id=? AND scene_id=? AND kind=?',(scene['selected_video_id'],scene['id'],'video'))
        if not asset:
            raise ValueError('A selected take no longer belongs to its scene.')
        metadata=json.loads(asset['metadata'])
        clips.append({'id':uid(),'scene_id':scene['id'],'asset_id':asset['id'],'trim_in':0,'trim_out':metadata['duration'],'speed':1,'volume':1,'mute':False,'transition':'cut'})
    timeline=project['timeline']
    return save_timeline(project_id,timeline['revision'],clips,timeline.get('audio',[]),{**timeline['settings'],'partial':len(clips)<len(project['scenes'])})


def save_timeline(project_id,revision,clips,audio,settings):
    if not 0 < len(clips) <= 200:
        raise ValueError('A timeline needs between one and 200 clips.')
    for clip in clips:
        asset=db.one('SELECT * FROM assets WHERE id=? AND project_id=? AND kind IN (?,?)',(clip.get('asset_id'),project_id,'video','image'))
        if not asset or asset['scene_id']!=clip.get('scene_id'):
            raise ValueError('A timeline clip must reference media from its own scene and project.')
        metadata=json.loads(asset['metadata'])
        duration=float(metadata.get('duration',clip.get('duration',5)))
        start=float(clip.get('trim_in',0));end=float(clip.get('trim_out',duration));speed=float(clip.get('speed',1))
        if not all(math.isfinite(v) for v in [start,end,speed]) or not 0<=start<end<=duration+.1 or not .25<=speed<=4:
            raise ValueError('Clip trims or playback speed are outside the source duration.')
    for track in audio:
        if not db.one('SELECT id FROM assets WHERE id=? AND project_id=? AND kind=?',(track.get('asset_id'),project_id,'audio')):
            raise ValueError('An audio track must belong to this project.')
    width=int(settings.get('width',1920));height=int(settings.get('height',1080));fps=int(settings.get('fps',30))
    if not 64<=width<=3840 or not 64<=height<=2160 or width%2 or height%2 or not 1<=fps<=60:
        raise ValueError('Choose an even export size up to 3840×2160 and a frame rate from 1 to 60.')
    if settings.get('fit','pad') not in ['pad','crop'] or settings.get('audio_mode','silent') not in ['silent','preserve','mixed']:
        raise ValueError('Invalid export fitting or audio policy.')
    if not 1<=int(settings.get('repeats',1))<=20:
        raise ValueError('Use between one and twenty loop repetitions.')
    body={'clips':clips,'audio':audio,'settings':settings}
    with db.connect(True) as con:
        row=con.execute('SELECT revision FROM timelines WHERE project_id=?',(project_id,)).fetchone()
        if not row or row['revision']!=revision:
            raise Conflict('The timeline changed in another view. Refresh before saving.')
        con.execute('UPDATE timelines SET revision=revision+1,body=?,updated=? WHERE project_id=?',(encode(body),now(),project_id))
    db.event('timeline.updated',{'project_id':project_id,'revision':revision+1})
    return {**body,'revision':revision+1}


def queue_export(project_id,automatic=False):
    from .production import pause,queue_snapshot
    project=db.project(project_id)
    timeline=project['timeline']
    if not timeline or not timeline['clips']:
        raise ValueError('Build and save a timeline before exporting.')
    frozen={'project_id':project_id,'scene_id':None,'title':project['title'],'timeline':timeline,'timeline_revision':timeline['revision']}
    for clip in timeline['clips']:
        path=asset_path(clip['asset_id'])
        asset=db.one('SELECT sha256,project_id FROM assets WHERE id=?',(clip['asset_id'],))
        if asset['project_id']!=project_id:
            raise ValueError('Export assets must belong to this project.')
        clip['source_sha256']=asset['sha256']
    pause(project_id,False)
    return queue_snapshot('export',frozen,automatic=automatic)


def execute_export(job,snapshot):
    timeline=snapshot['timeline'];settings=timeline['settings'];width=int(settings.get('width',1920));height=int(settings.get('height',1080));fps=int(settings.get('fps',30))
    root=ROOT/'temp'/('export-'+job['id']);root.mkdir(parents=True,exist_ok=True)
    normalized=[];expected=0
    for index,clip in enumerate(timeline['clips']):
        source=asset_path(clip['asset_id'])
        start=float(clip.get('trim_in',0));end=float(clip['trim_out']);speed=float(clip.get('speed',1));duration=(end-start)/speed
        fit='increase' if settings.get('fit')=='crop' else 'decrease'
        sizing=f'scale={width}:{height}:force_original_aspect_ratio={fit},'+(f'crop={width}:{height}' if fit=='increase' else f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black')
        output=root/f'{index:04d}.mp4'
        filters=f'setpts=(PTS-STARTPTS)/{speed},{sizing},setsar=1,fps={fps},format=yuv420p'
        run_tool([executable('ffmpeg'),'-y','-v','error','-ss',str(start),'-t',str(end-start),'-i',str(source),'-vf',filters,'-an','-c:v','libx264','-preset','fast','-crf',str(int(settings.get('crf',18))),'-threads','2','-movflags','+faststart',str(output)],timeout=600)
        normalized.append(output);expected+=duration
    listing=root/'clips.txt'
    # Generated internal filenames contain no user-supplied shell or concat syntax.
    listing.write_text('\n'.join("file '"+str(path).replace('\\','/')+"'" for path in normalized),encoding='utf-8')
    movie=root/'joined.mp4'
    run_tool([executable('ffmpeg'),'-y','-v','error','-f','concat','-safe','0','-i',str(listing),'-c','copy','-movflags','+faststart',str(movie)],timeout=600)
    if settings.get('audio_mode','silent')!='silent':
        raise ValueError('Audio mixing is not enabled until the editing phase. The silent intermediate is preserved.')
    validation=probe(movie)
    if validation['width']!=width or validation['height']!=height or abs(validation['duration']-expected)>max(.2,len(normalized)/fps) or validation['audio_streams']!=0:
        raise ValueError('The final movie did not pass resolution, duration, or audio validation.')
    partial=bool(settings.get('partial'))
    add_asset(job['project_id'],None,job['id'],'export',movie,extra={'title':('Partial preview · ' if partial else '')+snapshot['title'],'partial':partial,'timeline_revision':snapshot['timeline_revision'],'source_asset_ids':[c['asset_id'] for c in timeline['clips']],'validation':'decoded_and_probed','expected_duration':expected})
