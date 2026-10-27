"""CPU-only assembly from frozen, verified media references."""
import hashlib
import json
import math
import re
import shutil
from functools import lru_cache

from .config import ROOT,settings as studio_settings
from .media import add_asset,asset_path,executable,probe,run_tool
from .store import db


def verified_source(item):
    path=asset_path(item['asset_id'])
    with path.open('rb') as file:
        digest=hashlib.file_digest(file,'sha256').hexdigest()
    if digest!=item['source_sha256']:
        raise ValueError('A frozen export source changed on disk. Reimport it before creating a new export.')
    return path


def tempo(speed):
    pieces=[]
    while speed<.5:pieces.append('atempo=0.5');speed/=.5
    while speed>2:pieces.append('atempo=2');speed/=2
    pieces.append(f'atempo={speed}')
    return ','.join(pieces)


def ffmpeg(args,timeout=1200):
    return run_tool([executable('ffmpeg'),'-y','-v','error','-filter_complex_threads','1',*args],timeout=timeout)


def encode_options(settings):
    codec='libx265' if settings.get('codec')=='h265' else 'libx264'
    extra=['-x265-params','pools=2:frame-threads=2:log-level=error','-tag:v','hvc1'] if codec=='libx265' else []
    return ['-c:v',codec,*extra,'-preset','fast','-crf',str(int(settings.get('crf',18))),'-threads','2','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart']


@lru_cache(maxsize=4)
def filter_file_option(binary):
    match=re.search(r'version (?:n)?(\d+)',run_tool([binary,'-version']))
    return '-/filter_complex' if match and int(match[1])>=7 else '-filter_complex_script'


def execute(job,snapshot):
    if db.one("SELECT id FROM assets WHERE job_id=? AND kind='export'",(job['id'],)):
        return
    timeline=snapshot['timeline'];settings=timeline['settings'];clips=timeline['clips']
    width=int(settings.get('width',1920));height=int(settings.get('height',1080));fps=int(settings.get('fps',30))
    durations=[round((float(c['trim_out'])-float(c.get('trim_in',0)))/float(c.get('speed',1))*fps)/fps for c in clips]
    if min(durations)<1/fps:
        raise ValueError('A trimmed clip is shorter than one export frame.')
    expected=sum(durations)
    reserve=studio_settings['disk_reserve_gb']*1073741824+max(512*1024**2,expected*width*height*fps*.04)
    from .storage import export_folder
    root=export_folder(job['id']);root.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(root).free<reserve:
        raise ValueError('Not enough free project-drive space for export intermediates and the storage reserve.')
    normalized=[];has_audio=False
    # Normalize trim/speed/audio together; each clip has exactly one stereo track.
    for index,(clip,duration) in enumerate(zip(clips,durations)):
        source=verified_source(clip);asset=db.one('SELECT kind,metadata FROM assets WHERE id=?',(clip['asset_id'],));metadata=json.loads(asset['metadata'])
        start=float(clip.get('trim_in',0));span=float(clip['trim_out'])-start;speed=float(clip.get('speed',1))
        args=['-protocol_whitelist','file,pipe','-ss',str(start),'-t',str(span)]
        if asset['kind']=='image':args=['-loop','1','-t',str(span)]
        args+=['-i',str(source)]
        sidecar=clip.get('audio_asset_id') and not metadata.get('audio_streams') and not clip.get('mute') and settings.get('audio_mode','silent')!='silent'
        if sidecar:
            audio_path=verified_source({'asset_id':clip['audio_asset_id'],'source_sha256':clip['audio_source_sha256']})
            args+=['-protocol_whitelist','file,pipe','-ss',str(start),'-t',str(span),'-i',str(audio_path)]
        if (not metadata.get('audio_streams') and not sidecar) or clip.get('mute') or settings.get('audio_mode','silent')=='silent':
            args+=['-f','lavfi','-t',str(duration),'-i','anullsrc=r=48000:cl=stereo'];audio='1:a:0';audio_filter='asetpts=PTS-STARTPTS'
        else:
            has_audio=True;audio='1:a:0' if sidecar else '0:a:0';audio_filter=f"asetpts=PTS-STARTPTS,{tempo(speed)},volume={float(clip.get('volume',1))}"
        fit='increase' if settings.get('fit')=='crop' else 'decrease'
        sizing=f'scale={width}:{height}:force_original_aspect_ratio={fit},'+(f'crop={width}:{height}' if fit=='increase' else f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black')
        video=f'setpts=(PTS-STARTPTS)/{speed},{sizing},setsar=1,fps={fps},format=yuv420p'
        output=root/f'{index:04d}.mp4'
        ffmpeg(args+['-filter_complex',f'[0:v]{video}[v];[{audio}]{audio_filter},aresample=48000,apad[a]','-map','[v]','-map','[a]','-t',str(duration),*encode_options(settings),str(output)])
        normalized.append(output)
    args=[];filters=[]
    for index,path in enumerate(normalized):
        args+=['-i',str(path)]
        filters += [f'[{index}:v]settb=AVTB,setpts=PTS-STARTPTS[v{index}]',f'[{index}:a]asetpts=PTS-STARTPTS[a{index}]']
    video='v0';audio='a0';elapsed=durations[0]
    for index in range(1,len(clips)):
        transition=clips[index-1].get('transition','inherit')
        if transition=='inherit':transition=settings.get('transition','cut')
        next_video=f'jv{index}';next_audio=f'ja{index}'
        if transition=='cut':
            filters.append(f'[{video}][{audio}][v{index}][a{index}]concat=n=2:v=1:a=1[{next_video}][{next_audio}]')
            elapsed+=durations[index]
        else:
            length=min(float(settings.get('transition_duration',.35)),durations[index-1]/3,durations[index]/3)
            length=max(1/fps,round(length*fps)/fps)
            effect='fadeblack' if transition=='fade_black' else 'dissolve' if transition=='dissolve' else 'fade'
            filters.append(f'[{video}][v{index}]xfade=transition={effect}:duration={length}:offset={elapsed-length}[{next_video}]')
            filters.append(f'[{audio}][a{index}]acrossfade=d={length}:c1=tri:c2=tri[{next_audio}]')
            elapsed+=durations[index]-length
        video=next_video;audio=next_audio
    movie=root/'joined.mp4';script=root/'assembly.filters';script.write_text(';'.join(filters),encoding='utf-8')
    ffmpeg(args+[filter_file_option(executable('ffmpeg')),str(script),'-map',f'[{video}]','-map',f'[{audio}]','-t',str(elapsed),*encode_options(settings),str(movie)])
    expected=elapsed
    loop=settings.get('loop','none')
    if loop in ['fade_black','crossfade']:
        length=max(1/fps,round(min(.5,expected/4)*fps)/fps);output=root/'loop.mp4'
        if loop=='fade_black':
            graph=f'[0:v]fade=t=in:d={length},fade=t=out:st={expected-length}:d={length}[v];[0:a]afade=t=in:d={length},afade=t=out:st={expected-length}:d={length}[a]'
        else:
            graph=f'[0:v]split=3[body][tail][head];[body]trim=start={length}:end={expected-length},setpts=PTS-STARTPTS[b];[tail]trim=start={expected-length},setpts=PTS-STARTPTS[t];[head]trim=end={length},setpts=PTS-STARTPTS[h];[t][h]xfade=transition=fade:duration={length}:offset=0[x];[b][x]concat=n=2:v=1:a=0[v];[0:a]asplit=3[ab][at][ah];[ab]atrim=start={length}:end={expected-length},asetpts=PTS-STARTPTS[ba];[at]atrim=start={expected-length},asetpts=PTS-STARTPTS[ta];[ah]atrim=end={length},asetpts=PTS-STARTPTS[ha];[ta][ha]acrossfade=d={length}[xa];[ba][xa]concat=n=2:v=0:a=1[a]'
            expected-=length
        graph=graph.replace('[v]','[loopv]').replace('[a]','[loopa]')+f';[loopv]fps={fps},tpad=stop_mode=clone:stop_duration=1[v];[loopa]apad[a]'
        ffmpeg(['-i',str(movie),'-filter_complex',graph,'-map','[v]','-map','[a]','-t',str(expected),*encode_options(settings),str(output)]);movie=output
    repeats=int(settings.get('repeats',1))
    if repeats>1:
        output=root/'repeated.mp4';expected*=repeats
        ffmpeg(['-stream_loop',str(repeats-1),'-i',str(movie),'-vf',f'fps={fps},tpad=stop_mode=clone:stop_duration=1','-af','aresample=48000:async=1:first_pts=0,apad','-t',str(expected),*encode_options(settings),str(output)]);movie=output
    # Imported audio is mixed once after video assembly, so muxed clip audio is never doubled.
    tracks=timeline.get('audio',[]) if settings.get('audio_mode')=='mixed' else []
    if tracks:
        args=['-i',str(movie)];filters=['[0:a]anull[base]'];labels=['[base]']
        voice_intervals=[]
        for t in tracks:
            if t.get('role')=='voiceover' and not t.get('mute'):
                span=float(t['trim_out'])-float(t.get('trim_in',0));voice_intervals.append((float(t.get('start',0)),float(t.get('start',0))+span))
        for index,track in enumerate(tracks,1):
            source=verified_source(track);start=float(track.get('start',0));span=float(track['trim_out'])-float(track.get('trim_in',0))
            args+=['-protocol_whitelist','file,pipe','-i',str(source)]
            volume=0 if track.get('mute') else float(track.get('volume',1))
            chain=f"[{index}:a]atrim=start={float(track.get('trim_in',0))}:end={float(track['trim_out'])},asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo,volume={volume}"
            fade_in=min(float(track.get('fade_in',0)),span);fade_out=min(float(track.get('fade_out',0)),span)
            if fade_in:chain+=f',afade=t=in:d={fade_in}'
            if fade_out:chain+=f',afade=t=out:st={span-fade_out}:d={fade_out}'
            chain+=f',adelay={round(start*1000)}:all=1'
            if track.get('duck') and track.get('role')=='music' and voice_intervals:
                condition='+'.join(f'between(t\\,{a}\\,{b})' for a,b in voice_intervals)
                chain+=f",volume='if({condition}\\,0.3\\,1)':eval=frame"
            label=f't{index}';filters.append(chain+f'[{label}]');labels.append(f'[{label}]')
            has_audio=has_audio or not track.get('mute')
        filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=first:normalize=0,alimiter=limit=0.95[mix]')
        output=root/'mixed.mp4';script=root/'audio.filters';script.write_text(';'.join(filters),encoding='utf-8')
        ffmpeg(args+[filter_file_option(executable('ffmpeg')),str(script),'-map','0:v:0','-map','[mix]','-t',str(expected),'-c:v','copy','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',str(output)]);movie=output
    silent=settings.get('audio_mode','silent')=='silent' or not has_audio
    if silent:
        output=root/'silent.mp4';ffmpeg(['-i',str(movie),'-map','0:v:0','-an','-c:v','copy','-movflags','+faststart',str(output)]);movie=output
    validation=probe(movie)
    if validation['width']!=width or validation['height']!=height or abs(validation['fps']-fps)>.02 or abs(validation['duration']-expected)>max(.25,len(clips)/fps) or validation['audio_streams']!=(0 if silent else 1):
        raise ValueError(f'Export validation failed: observed {validation}; expected {width}x{height}, {fps} fps, {expected:.6f} seconds, {0 if silent else 1} audio tracks.')
    partial=bool(settings.get('partial'))
    add_asset(job['project_id'],None,job['id'],'export',movie,extra={'title':('Partial preview · ' if partial else '')+snapshot['title'],'partial':partial,'is_editing_preview':snapshot.get('is_editing_preview',False),'timeline_revision':snapshot['timeline_revision'],'source_asset_ids':[c['asset_id'] for c in clips],'validation':'decoded_and_probed','expected_duration':expected,'export_settings':settings,'loop_note':'Crossfade blends the boundary; it cannot guarantee matching scene content.','audio_tracks':len(tracks)})
