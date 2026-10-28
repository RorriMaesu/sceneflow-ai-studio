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
    from .media import export_owner
    from .storage import export_folder
    folder=export_folder(job['id']);folder.mkdir(parents=True,exist_ok=True)
    token=export_owner.set({'job_id':job['id'],'store':db,'folder':folder})
    try:return render(job,snapshot)
    finally:export_owner.reset(token)


def render(job,snapshot):
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
    from .render_cache import RenderCache
    cache=RenderCache(job,db,{'width':width,'height':height,'fps':fps,'codec':settings.get('codec','h264'),'crf':settings.get('crf',18),'fit':settings.get('fit','pad')})
    normalized=[];has_audio=False;verified={}
    def source_for(item):
        key=(item['asset_id'],item['source_sha256'])
        if key not in verified:verified[key]=verified_source(item)
        return verified[key]
    def intermediate_options():
        options=encode_options(settings)
        at=options.index('-c:a');options[at+1]='alac'
        return options+['-video_track_timescale',str(fps*1000)]
    def progress(value):
        db.execute('UPDATE jobs SET progress=? WHERE id=?',(value,job['id']))

    # Normalize trim/speed/audio together; each clip has exactly one stereo track.
    for index,(clip,duration) in enumerate(zip(clips,durations)):
        source=source_for(clip);asset=db.one('SELECT kind,metadata FROM assets WHERE id=?',(clip['asset_id'],));metadata=json.loads(asset['metadata'])
        start=float(clip.get('trim_in',0));span=float(clip['trim_out'])-start;speed=float(clip.get('speed',1))
        args=['-protocol_whitelist','file,pipe','-ss',str(start),'-t',str(span)]
        if asset['kind']=='image':args=['-loop','1','-t',str(span)]
        args+=['-i',str(source)]
        sidecar=clip.get('audio_asset_id') and not metadata.get('audio_streams') and not clip.get('mute') and settings.get('audio_mode','silent')!='silent'
        if sidecar:
            audio_path=source_for({'asset_id':clip['audio_asset_id'],'source_sha256':clip['audio_source_sha256']})
            args+=['-protocol_whitelist','file,pipe','-ss',str(start),'-t',str(span),'-i',str(audio_path)]
        if (not metadata.get('audio_streams') and not sidecar) or clip.get('mute') or settings.get('audio_mode','silent')=='silent':
            args+=['-f','lavfi','-t',str(duration),'-i','anullsrc=r=48000:cl=stereo'];audio='1:a:0';audio_filter='asetpts=PTS-STARTPTS'
        else:
            has_audio=True;audio='1:a:0' if sidecar else '0:a:0';audio_filter=f"asetpts=PTS-STARTPTS,{tempo(speed)},volume={float(clip.get('volume',1))}"
        fit='increase' if settings.get('fit')=='crop' else 'decrease'
        sizing=f'scale={width}:{height}:force_original_aspect_ratio={fit},'+(f'crop={width}:{height}' if fit=='increase' else f'pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black')
        video=f'setpts=(PTS-STARTPTS)/{speed},{sizing},setsar=1,fps={fps},format=yuv420p'
        frames=round(duration*fps)
        # Lossless audio in intermediates avoids AAC encoder delay at every edit.
        graph=f'[0:v]{video},tpad=stop_mode=clone:stop_duration=1[v];[{audio}]{audio_filter},aresample=48000,apad,atrim=end_sample={round(duration*48000)}[a]'
        recipe={'stage':'normalize','source':clip['source_sha256'],'kind':asset['kind'],'start':start,'span':span,'speed':speed,'graph':graph,'sidecar':clip.get('audio_source_sha256')}
        node=cache.section(recipe,frames,lambda output:ffmpeg(args+['-filter_complex',graph,'-map','[v]','-map','[a]','-t',str(duration),'-frames:v',str(frames),*intermediate_options(),str(output)]),inputs=2)
        normalized.append({**node,'first':index,'last':index})
        progress(.05+.45*(index+1)/len(clips))
    def boundary(index):
        choice=clips[index].get('transition','inherit')
        return settings.get('transition','cut') if choice=='inherit' else choice
    def combine(nodes,transition='cut'):
        frames=sum(n['frames'] for n in nodes)
        fade_frames=0
        if transition!='cut':
            boundary_index=nodes[0]['last']
            fade_frames=max(1,round(min(float(settings.get('transition_duration',.35)),durations[boundary_index]/3,durations[boundary_index+1]/3)*fps))
            frames-=fade_frames
        def build(output):
            if transition=='cut':
                # Relative cache names contain only hex digits; durations are explicit.
                listing=root/('concat-'+nodes[0]['key'][:12]+'-'+nodes[-1]['key'][:12]+'.txt')
                listing.write_text(''.join("file '"+str(n['path']).replace('\\','/').replace("'", "'\\''")+"'\nduration "+str(n['frames']/fps)+"\n" for n in nodes),encoding='utf-8')
                ffmpeg(['-f','concat','-safe','0','-i',str(listing),'-map','0:v:0','-map','0:a:0','-c:v','copy','-af',f'aresample=48000:async=1:first_pts=0,apad,atrim=end_sample={round(frames/fps*48000)}','-c:a','alac','-ar','48000','-ac','2','-t',str(frames/fps),'-video_track_timescale',str(fps*1000),str(output)],timeout=7200)
            else:
                length=fade_frames/fps;effect='fadeblack' if transition=='fade_black' else 'dissolve' if transition=='dissolve' else 'fade'
                graph=f'[0:v]settb=AVTB,setpts=PTS-STARTPTS[l];[1:v]settb=AVTB,setpts=PTS-STARTPTS[r];[l][r]xfade=transition={effect}:duration={length}:offset={nodes[0]["frames"]/fps-length},fps={fps},tpad=stop_mode=clone:stop_duration=1[v];[0:a][1:a]acrossfade=d={length}:c1=tri:c2=tri,apad,atrim=end_sample={round(frames/fps*48000)}[a]'
                ffmpeg(['-i',str(nodes[0]['path']),'-i',str(nodes[1]['path']),'-filter_complex',graph,'-map','[v]','-map','[a]','-frames:v',str(frames),'-t',str(frames/fps),*intermediate_options(),str(output)],timeout=7200)
        result=cache.section({'stage':'join','nodes':[n['key'] for n in nodes],'transition':transition,'fade_frames':fade_frames},frames,build,inputs=len(nodes))
        return {**result,'first':nodes[0]['first'],'last':nodes[-1]['last']}
    nodes=normalized
    cuts=all(boundary(i)=='cut' for i in range(len(clips)-1))
    while len(nodes)>1:
        next_level=[];size=8 if cuts else 2
        for offset in range(0,len(nodes),size):
            group=nodes[offset:offset+size]
            next_level.append(group[0] if len(group)==1 else combine(group,'cut' if cuts else boundary(group[0]['last'])))
        nodes=next_level;progress(.6)
    movie=nodes[0]['path'];elapsed=nodes[0]['frames']/fps
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
        voice_intervals=[]
        for t in tracks:
            if t.get('role')=='voiceover' and not t.get('mute'):
                span=float(t['trim_out'])-float(t.get('trim_in',0));voice_intervals.append((float(t.get('start',0)),float(t.get('start',0))+span))
        current_mix=movie
        # At most seven new tracks plus the previous sum are opened together.
        for offset in range(0,len(tracks),7):
            batch=tracks[offset:offset+7];args=['-i',str(current_mix)];filters=['[0:a]anull[base]'];labels=['[base]']
            for index,track in enumerate(batch,1):
                source=source_for(track);start=float(track.get('start',0));span=float(track['trim_out'])-float(track.get('trim_in',0))
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
            final=offset+len(batch)==len(tracks)
            tail=',alimiter=limit=0.95' if final else ''
            filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=first:normalize=0'+tail+'[mix]')
            output=root/f'mix-{offset:04d}.wav';script=root/'audio.filters';script.write_text(';'.join(filters),encoding='utf-8')
            ffmpeg(args+[filter_file_option(executable('ffmpeg')),str(script),'-map','[mix]','-t',str(expected),'-c:a','pcm_f32le','-ar','48000','-ac','2',str(output)],timeout=7200)
            if current_mix!=movie:current_mix.unlink(missing_ok=True)
            current_mix=output
        output=root/'mixed.mp4'
        ffmpeg(['-i',str(movie),'-i',str(current_mix),'-map','0:v:0','-map','1:a:0','-t',str(expected),'-c:v','copy','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',str(output)],timeout=7200);movie=output
        current_mix.unlink(missing_ok=True)
    # Convert lossless intermediate audio exactly once for delivery.
    if not tracks:
        output=root/'delivery.mp4';ffmpeg(['-i',str(movie),'-map','0:v:0','-map','0:a:0','-c:v','copy','-c:a','aac','-ar','48000','-ac','2','-movflags','+faststart',str(output)],timeout=7200);movie=output
    progress(.9)
    silent=settings.get('audio_mode','silent')=='silent' or not has_audio
    if silent:
        output=root/'silent.mp4';ffmpeg(['-i',str(movie),'-map','0:v:0','-an','-c:v','copy','-movflags','+faststart',str(output)]);movie=output
    subtitle_items=snapshot.get('captions',[])
    if subtitle_items:
        from .music_planning import subtitle_text
        if any(item['end']>expected+.25 for item in subtitle_items):raise ValueError('Captions extend past the video. Trim their times or lengthen your saved edit before exporting.')
        subtitle=root/'captions.srt';subtitle.write_text(subtitle_text(subtitle_items),encoding='utf-8')
        output=root/'captioned.mp4'
        ffmpeg(['-i',str(movie),'-f','srt','-i',str(subtitle),'-map','0:v:0','-map','0:a?','-map','1:0','-c:v','copy','-c:a','copy','-c:s','mov_text','-metadata:s:s:0','language=und','-movflags','+faststart',str(output)])
        movie=output
    validation=probe(movie)
    if validation.get('av_duration_difference',0)>max(.05,1/fps):raise ValueError('The finished audio and video lengths differ. Completed sections are kept; inspect the source timing before retrying.')
    if validation.get('subtitle_streams',0)!=(1 if subtitle_items else 0):raise ValueError('The finished video did not contain the expected caption track.')
    if validation['width']!=width or validation['height']!=height or abs(validation['fps']-fps)>.02 or abs(validation['duration']-expected)>max(.25,len(clips)/fps) or validation['audio_streams']!=(0 if silent else 1):
        raise ValueError(f'Export validation failed: observed {validation}; expected {width}x{height}, {fps} fps, {expected:.6f} seconds, {0 if silent else 1} audio tracks.')
    partial=bool(settings.get('partial'))
    add_asset(job['project_id'],None,job['id'],'export',movie,extra={'title':('Partial preview · ' if partial else '')+snapshot['title'],'partial':partial,'is_editing_preview':snapshot.get('is_editing_preview',False),'timeline_revision':snapshot['timeline_revision'],'caption_revision':snapshot.get('caption_revision',0),'source_asset_ids':[c['asset_id'] for c in clips],'validation':'decoded_and_probed','expected_duration':expected,'export_settings':settings,'loop_note':'Crossfade blends the boundary; it cannot guarantee matching scene content.','audio_tracks':len(tracks),'render_cache':cache.stats,'master_sequences':snapshot.get('master_sequences',[])})
