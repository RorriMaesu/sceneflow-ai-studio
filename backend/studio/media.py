import hashlib
import json
import os
import shutil
import subprocess
import psutil
from pathlib import Path, PureWindowsPath

from PIL import Image

from .config import ROOT, settings
from .store import db, encode, now, uid


def managed_path(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_relative_to((ROOT / 'projects').resolve()):
        raise ValueError('This file is outside managed project storage.')
    return path


def asset_path(identifier):
    row = db.one('SELECT * FROM assets WHERE id=?', (identifier,))
    if not row:
        raise KeyError('Asset not found')
    path = managed_path(row['path'])
    if not path.is_file():
        raise FileNotFoundError('The selected media file is missing from project storage.')
    return path


def executable(kind):
    value = settings.get(kind)
    if value and Path(value).is_file() and Path(value).name.lower().startswith(kind):
        return value
    root = ROOT / 'tools' / 'ffmpeg'
    matches = list(root.rglob(kind+'.exe')) if root.exists() else []
    if matches:
        settings[kind] = str(matches[0])
        return str(matches[0])
    system = shutil.which(kind)
    if system:
        return system
    raise ValueError(f'{kind} is unavailable. Add the portable media tools in Studio settings.')


def run_tool(arguments, timeout=180):
    environment = {**os.environ, 'TEMP': str(ROOT/'temp'), 'TMP': str(ROOT/'temp')}
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace', env=environment, cwd=ROOT/'temp', creationflags=0x08000000 if os.name=='nt' else 0)
    marker=None
    for argument in arguments[1:]:
        try:
            relative=Path(str(argument)).resolve().relative_to((ROOT/'temp').resolve())
            if relative.parts and relative.parts[0].startswith('export-'):
                marker=ROOT/'temp'/relative.parts[0]/'worker.json'
                marker.write_text(encode({'pid':process.pid,'created':psutil.Process(process.pid).create_time(),'binary':str(Path(arguments[0]).resolve())}),encoding='utf-8');break
        except (ValueError,OSError,psutil.Error):pass
    try:
        output,error=process.communicate(timeout=timeout)
        if process.returncode:raise ValueError('Media processing failed: '+error[-1500:])
        return output
    except subprocess.TimeoutExpired:
        process.kill();process.communicate()
        raise ValueError('Media processing timed out. The owned worker was stopped; source media is preserved.')
    finally:
        if marker:marker.unlink(missing_ok=True)


def probe(path, decode=True):
    safe_inputs=['-protocol_whitelist','file,pipe','-format_whitelist','mov,matroska,webm,wav,mp3,flac,ogg,aac,avi']
    data = json.loads(run_tool([executable('ffprobe'), '-v', 'error', *safe_inputs, '-show_format', '-show_streams', '-count_frames', '-of', 'json', str(path)]))
    videos = [s for s in data['streams'] if s['codec_type']=='video']
    audios = [s for s in data['streams'] if s['codec_type']=='audio']
    result = {'duration': float(data.get('format', {}).get('duration', 0)), 'bytes': path.stat().st_size, 'audio_streams': len(audios), 'audio': [{'sample_rate': s.get('sample_rate'), 'channels': s.get('channels'), 'channel_layout': s.get('channel_layout')} for s in audios]}
    if videos:
        stream = videos[0]
        numerator, denominator = stream.get('avg_frame_rate', '0/1').split('/')
        result.update(width=stream['width'], height=stream['height'], fps=float(numerator)/float(denominator or 1), frames=int(stream.get('nb_read_frames', stream.get('nb_frames', 0)) or 0), codec=stream['codec_name'])
    if decode:
        run_tool([executable('ffmpeg'), '-v', 'error', '-xerror', *safe_inputs, '-i', str(path), '-map', '0:v?', '-map', '0:a?', '-f', 'null', '-'], timeout=300)
    return result


def verify(path, kind):
    if not path.is_file() or path.stat().st_size == 0:
        raise ValueError('The generated media file is empty or missing.')
    if kind == 'image':
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.width*image.height > 67108864 or max(image.size)>16384:
                raise ValueError('The image exceeds the 64-megapixel import limit.')
            image.load()
            return {'width': image.width, 'height': image.height, 'format': image.format, 'bytes': path.stat().st_size}
    result = probe(path)
    if kind in ['video', 'export'] and (result.get('frames', 0) == 0 or result['duration'] <= 0):
        raise ValueError('The generated video could not be decoded into frames.')
    if kind == 'audio' and result['audio_streams'] == 0:
        raise ValueError('The imported audio contains no audio track.')
    return result


def add_asset(project_id, scene_id, job_id, kind, incoming, source_asset_id=None, extra=None):
    if source_asset_id:
        source = db.one('SELECT * FROM assets WHERE id=?', (source_asset_id,))
        if not source or source['project_id'] != project_id or (scene_id and source['scene_id'] != scene_id):
            raise ValueError('The source asset does not belong to this scene and project.')
    identifier = uid()
    suffix = incoming.suffix.lower()
    relative = Path('projects') / project_id / ('exports' if kind=='export' else 'scenes')
    if scene_id:
        relative = relative / scene_id / (kind+'s')
    relative = relative / (identifier+suffix)
    destination = managed_path(relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix+'.part')
    shutil.copyfile(incoming, temporary)
    metadata = {**verify(temporary, kind), **(extra or {})}
    if job_id and kind in ['image','video']:
        job=db.one('SELECT snapshot FROM jobs WHERE id=?',(job_id,))
        expected=json.loads(job['snapshot']) if job else {}
        if all(k in expected for k in ['width','height']) and (metadata.get('width')!=expected['width'] or metadata.get('height')!=expected['height']):
            raise ValueError('Generated dimensions do not match the frozen workflow request.')
        if kind=='video' and 'frames' in expected and (abs(metadata.get('frames',0)-expected['frames'])>1 or abs(metadata.get('fps',0)-expected['fps'])>.1):
            raise ValueError('Generated frame count or frame rate does not match the frozen workflow request.')
    with temporary.open('rb') as file:
        digest = hashlib.file_digest(file, 'sha256').hexdigest()
    os.replace(temporary, destination)
    try:
        db.execute('INSERT INTO assets(id,project_id,scene_id,job_id,source_asset_id,kind,path,sha256,metadata,created) VALUES(?,?,?,?,?,?,?,?,?,?)', (identifier, project_id, scene_id, job_id, source_asset_id, kind, str(relative), digest, encode(metadata), now()))
    except BaseException:
        destination.rename(destination.with_suffix(destination.suffix+'.unverified'))
        raise
    db.event('asset.created', {'project_id': project_id, 'scene_id': scene_id, 'asset_id': identifier})
    if kind=='image':
        with Image.open(destination) as image:
            thumbnail=image.convert('RGB')
            thumbnail.thumbnail((320,320))
            thumbnail.save(destination.with_suffix('.thumbnail.jpg'), quality=85)
    return db.one('SELECT * FROM assets WHERE id=?', (identifier,))


def select_asset(identifier, approve=False):
    row = db.one('SELECT * FROM assets WHERE id=?', (identifier,))
    if not row:
        raise KeyError('Asset not found')
    if row['kind'] not in ['image','video'] or not row['scene_id']:
        raise ValueError('Select a scene image or video take.')
    asset_path(identifier)
    field = 'selected_image_id' if row['kind']=='image' else 'selected_video_id'
    from .production import stage_signature
    scene=db.scene(row['scene_id']);signature=stage_signature(scene,{'settings':json.loads(db.one('SELECT settings FROM projects WHERE id=?',(row['project_id'],))['settings'])},row['kind'])
    with db.connect(True) as con:
        if row['kind']=='video' and row['source_asset_id'] and scene['selected_image_id']!=row['source_asset_id']:
            con.execute('UPDATE scenes SET selected_image_id=? WHERE id=?',(row['source_asset_id'],scene['id']))
            image_signature=stage_signature(scene,{'settings':json.loads(db.one('SELECT settings FROM projects WHERE id=?',(row['project_id'],))['settings'])},'image')
            con.execute('INSERT OR REPLACE INTO asset_selections VALUES(?,?,?,?)',(scene['id'],'image',row['source_asset_id'],image_signature))
            scene['selected_image_id']=row['source_asset_id']
            signature=stage_signature(scene,{'settings':json.loads(db.one('SELECT settings FROM projects WHERE id=?',(row['project_id'],))['settings'])},'video')
        con.execute(f'UPDATE scenes SET {field}=?,updated=? WHERE id=? AND project_id=?', (identifier, now(), row['scene_id'], row['project_id']))
        con.execute('INSERT OR REPLACE INTO asset_selections VALUES(?,?,?,?)',(row['scene_id'],row['kind'],identifier,signature))
        if approve:
            con.execute('UPDATE assets SET approved=1,approval_source=? WHERE id=?', ('user', identifier))
    db.event('asset.selected', {'project_id': row['project_id'], 'scene_id': row['scene_id'], 'asset_id': identifier})
    return {'selected': identifier, 'approved': bool(approve or row['approved'])}


def validate_comfy_reference(item):
    filename = item.get('filename', '')
    folder = item.get('subfolder', '')
    if not filename or Path(filename).name != filename or PureWindowsPath(filename).name != filename or any(x in filename for x in [':', '\\', '/', '\x00']):
        raise ValueError('The backend returned an unsafe output filename.')
    if PureWindowsPath(folder).is_absolute() or ':' in folder or '..' in folder.replace('\\','/').split('/'):
        raise ValueError('The backend returned an unsafe output folder.')
    if item.get('type') not in ['output', 'temp']:
        raise ValueError('The backend returned an unexpected output location.')
    return {'filename': filename, 'subfolder': folder, 'type': item['type']}


async def collect_outputs(client, job, result, entry):
    from .config import settings
    existing = db.all('SELECT * FROM assets WHERE job_id=?', (job['id'],))
    snapshot = json.loads(job['snapshot']) if isinstance(job['snapshot'], str) else job['snapshot']
    outputs = result.get('outputs', {})
    collected = list(existing)
    submitted=ROOT/'projects'/job['project_id']/'scenes'/job['scene_id']/'manifests'/(job['id']+'.submitted.json')
    provenance=json.loads(submitted.read_text(encoding='utf-8')) if submitted.is_file() else {}
    for key in entry['output_nodes']:
        output = outputs.get(str(key), {})
        items = output.get('images', []) + output.get('gifs', []) + output.get('audio', [])
        for item in items:
            params = validate_comfy_reference(item)
            suffix = Path(params['filename']).suffix.lower()
            kind = 'image' if suffix in ['.png','.jpg','.jpeg','.webp'] else 'video' if suffix in ['.mp4','.webm','.mkv'] else 'audio' if suffix in ['.wav','.flac','.mp3','.ogg'] else None
            if kind is None or (job['kind']=='image' and kind!='image') or (job['kind']=='video' and kind not in ['video','audio']):
                continue
            reference={'node':str(key),**params}
            if any(json.loads(a['metadata']).get('output_reference')==reference for a in existing):continue
            if len(items)==1 and len(entry['output_nodes'])==1 and any(a['kind']==kind and not json.loads(a['metadata']).get('output_reference') for a in existing):continue
            path = ROOT / 'temp' / (uid()+suffix)
            async with client.stream('GET', settings['comfy_url']+'/view', params=params, timeout=120) as response:
                response.raise_for_status()
                with path.open('wb') as file:
                    async for chunk in response.aiter_bytes(1024*1024):
                        file.write(chunk)
            import asyncio
            asset = await asyncio.to_thread(add_asset, job['project_id'], job['scene_id'], job['id'], kind, path, snapshot.get('source_asset_id'), {'comfy_prompt_id': job['comfy_prompt_id'], 'scene_revision_id': snapshot['scene_revision_id'], 'workflow_hash': snapshot['workflow_hash'], 'submitted_workflow_hash':provenance.get('workflow_hash'),'software':provenance.get('software',{}),'output_reference':{'node':str(key),**params}, 'source_sha256': snapshot.get('source_sha256')})
            collected.append(asset)
            path.unlink(missing_ok=True)
    if not any(a['kind']==job['kind'] for a in collected):
        raise ValueError('The expected output node returned no valid media for this exact job.')
    return collected
