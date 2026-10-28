"""Portable project bundles: no credentials, executable tools, or automatic work on restore."""
import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path,PureWindowsPath

from .config import ROOT,settings
from .media import asset_path,managed_path,verify
from .store import db,encode,now,uid

TABLES={'scenes':'project_id','scene_revisions':'scene_id','jobs':'project_id','assets':'project_id','chat':'project_id'}


def create_bundle(project_id):
    project=db.one('SELECT * FROM projects WHERE id=?',(project_id,))
    if not project:raise KeyError('Project not found')
    from .script_audio import migrate as sound_migrate
    from .music_planning import migrate as editing_migrate
    sound_migrate(db);editing_migrate(db)
    from .storage import role_folder
    identifier=uid();destination=role_folder('backups')/(identifier+'.sceneflow.zip');temporary=destination.with_suffix('.part')
    # One SQLite read transaction gives a consistent snapshot while the dispatcher works.
    with db.connect() as con:
        con.execute('BEGIN')
        project=dict(con.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone())
        manifest={'format':'sceneflow-project','version':1,'created':now(),'project':project,'tables':{}}
        for table,column in TABLES.items():
            if table=='scene_revisions':
                rows=con.execute('SELECT * FROM scene_revisions WHERE scene_id IN (SELECT id FROM scenes WHERE project_id=?)',(project_id,))
            else:rows=con.execute(f'SELECT * FROM {table} WHERE {column}=?',(project_id,))
            manifest['tables'][table]=[dict(row) for row in rows]
        timeline=con.execute('SELECT * FROM timelines WHERE project_id=?',(project_id,)).fetchone();manifest['timeline']=dict(timeline)
        from .script_audio import bundle_snapshot
        manifest['sound']=bundle_snapshot(con,project_id)
        if manifest['sound'] and any(manifest['sound'].values()):manifest['version']=2
        from .music_planning import bundle_snapshot as editing_snapshot
        manifest['editing']=editing_snapshot(con,project_id)
        if manifest['editing'] and any(manifest['editing'].values()):
            manifest['version']=3
            source=manifest['editing']['source_asset']
            if source and not any(a['id']==source['id'] for a in manifest['tables']['assets']):
                source={**source,'project_id':project_id,'scene_id':None,'job_id':None,'source_asset_id':None}
                manifest['tables']['assets'].append(source)
    try:
        with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
            for asset in manifest['tables']['assets']:
                path=asset_path(asset['id'])
                with path.open('rb') as file:digest=hashlib.file_digest(file,'sha256').hexdigest()
                if digest!=asset['sha256']:raise ValueError('A project asset changed on disk. Repair it before backing up.')
                name='media/'+asset['id']+path.suffix
                asset['bundle_path']=name;archive.write(path,name)
            archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False))
        os.replace(temporary,destination)
    except BaseException:
        temporary.unlink(missing_ok=True);raise
    db.event('backup.created',{'project_id':project_id,'backup_id':identifier})
    return {'id':identifier,'filename':destination.name,'bytes':destination.stat().st_size}


def remap(value,mapping):
    if isinstance(value,str):return mapping.get(value,value)
    if isinstance(value,list):return [remap(v,mapping) for v in value]
    if isinstance(value,dict):return {mapping.get(k,k):remap(v,mapping) for k,v in value.items()}
    return value


def restore_bundle(path):
    with zipfile.ZipFile(path) as archive:
        entries=archive.infolist()
        if len(entries)>15000 or sum(e.file_size for e in entries)>10*1024**3:
            raise ValueError('The bundle exceeds the supported 10 GB or 15,000-file restore limit.')
        names=[e.filename for e in entries]
        if shutil.disk_usage(ROOT).free<sum(e.file_size for e in entries)+settings['disk_reserve_gb']*1024**3:
            raise ValueError('Not enough project-drive space to restore this bundle and keep the storage reserve.')
        if len(names)!=len(set(names)):raise ValueError('Duplicate filenames in bundle.')
        for entry in entries:
            name=entry.filename
            if ':' in name or '\\' in name or name.startswith('/') or '..' in name.split('/') or PureWindowsPath(name).is_absolute() or (entry.external_attr>>16)&0o170000==0o120000:
                raise ValueError('Unsafe file entry in project bundle.')
        if 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>50*1024**2:
            raise ValueError('The bundle has no supported project manifest.')
        manifest=json.loads(archive.read('manifest.json'))
        if manifest.get('format')!='sceneflow-project' or manifest.get('version') not in [1,2,3] or set(manifest.get('tables',{}))!=set(TABLES) or manifest.get('version')==2 and not manifest.get('sound') or manifest.get('version')==3 and not manifest.get('editing'):
            raise ValueError('Unsupported project bundle format.')
        original=manifest['project'];mapping={original['id']:uid()}
        tables=manifest['tables']
        for table in TABLES:
            for row in tables[table]:
                old=row['id']
                if old in mapping:raise ValueError('Bundle identifiers must be globally unique.')
                mapping[old]=uid()
        project_id=mapping[original['id']];root=ROOT/'projects'/project_id
        if root.exists():raise ValueError('Restore target already exists.')
        root.mkdir(parents=True)
        try:
            for asset in tables['assets']:
                name=asset['bundle_path']
                if not name.startswith('media/') or name.count('/')!=1 or name not in names or Path(name).suffix.lower() not in ['.png','.jpg','.jpeg','.webp','.mp4','.webm','.mkv','.mov','.wav','.mp3','.flac','.ogg','.m4a']:
                    raise ValueError('Unsupported or missing bundled media.')
                relative=Path('projects')/project_id/'restored'/(mapping[asset['id']]+Path(name).suffix.lower());destination=managed_path(relative);destination.parent.mkdir(parents=True,exist_ok=True)
                with archive.open(name) as source,destination.open('wb') as target:shutil.copyfileobj(source,target,1024*1024)
                with destination.open('rb') as file:digest=hashlib.file_digest(file,'sha256').hexdigest()
                if digest!=asset['sha256']:raise ValueError('A bundled media hash failed validation.')
                if asset['kind'] not in ['image','video','audio','export']:raise ValueError('Unsupported bundled asset type.')
                measured=verify(destination,asset['kind']);asset['metadata']=encode({**json.loads(asset['metadata']),**measured});asset['path']=str(relative);asset.pop('bundle_path')
            # Validate all ownership and references before inserting any restored rows.
            scene_ids={r['id'] for r in tables['scenes']};asset_ids={r['id'] for r in tables['assets']}
            asset_rows={r['id']:r for r in tables['assets']};revisions={r['id']:r for r in tables['scene_revisions']};job_ids={r['id'] for r in tables['jobs']}
            if any(r['scene_id'] not in scene_ids for r in revisions.values()):raise ValueError('Cross-project creative revision in bundle.')
            if any(r['scene_id'] and r['scene_id'] not in scene_ids for r in tables['jobs']):raise ValueError('Cross-project job in bundle.')
            def check_references(values):
                identifiers=values.get('reference_asset_ids',[])
                if not isinstance(identifiers,list) or len(identifiers)>3 or any(not isinstance(v,str) or v not in asset_rows or asset_rows[v]['kind']!='image' for v in identifiers):raise ValueError('A bundled visual reference is missing or belongs outside this project.')
                if values.get('ending_asset_id') and (values['ending_asset_id'] not in asset_rows or asset_rows[values['ending_asset_id']]['kind']!='image'):raise ValueError('A bundled ending frame is missing or not an image.')
            check_references(json.loads(original['settings']))
            for row in tables['scenes']:check_references(json.loads(row['body']))
            for row in tables['scene_revisions']:check_references(json.loads(row['body']))
            for row in tables['jobs']:
                frozen=json.loads(row['snapshot']);check_references(frozen)
                for ref in frozen.get('reference_assets',[]):
                    if ref.get('id') not in asset_rows or ref.get('sha256')!=asset_rows[ref['id']]['sha256']:raise ValueError('A bundled reference hash does not match its media.')
                if frozen.get('mask_asset_id') and (frozen['mask_asset_id'] not in asset_rows or frozen.get('mask_sha256')!=asset_rows[frozen['mask_asset_id']]['sha256']):raise ValueError('A bundled correction mask is missing or changed.')
                if frozen.get('ending_asset_id') and frozen.get('ending_sha256')!=asset_rows[frozen['ending_asset_id']]['sha256']:raise ValueError('A bundled ending-frame hash does not match its image.')
            for table in ['scenes','jobs','assets','chat']:
                if any(r['project_id']!=original['id'] for r in tables[table]):raise ValueError('Cross-project rows in bundle.')
            for row in tables['assets']:
                if row['scene_id'] and row['scene_id'] not in scene_ids:raise ValueError('Invalid media ownership in bundle.')
                if row['source_asset_id'] and row['source_asset_id'] not in asset_ids:raise ValueError('Missing source asset in bundle.')
                if row['source_asset_id'] and asset_rows[row['source_asset_id']]['scene_id']!=row['scene_id']:raise ValueError('A bundled source asset belongs to another scene.')
                if row['job_id'] and row['job_id'] not in job_ids:raise ValueError('Missing bundled job provenance.')
            for row in tables['scenes']:
                if any(row.get(k) and row[k] not in asset_ids for k in ['selected_image_id','selected_video_id']):raise ValueError('Missing selected take in bundle.')
                if row['revision_id'] not in revisions or revisions[row['revision_id']]['scene_id']!=row['id']:raise ValueError('Scene revision ownership does not match.')
                for field,kind in [('selected_image_id','image'),('selected_video_id','video')]:
                    if row.get(field) and (asset_rows[row[field]]['scene_id']!=row['id'] or asset_rows[row[field]]['kind']!=kind):raise ValueError('Selected take ownership does not match.')
            timeline=json.loads(manifest['timeline']['body'])
            for clip in timeline['clips']:
                if clip['asset_id'] not in asset_rows or asset_rows[clip['asset_id']]['scene_id']!=clip['scene_id']:raise ValueError('Timeline references media outside this bundled scene.')
            for track in timeline.get('audio',[]):
                if track['asset_id'] not in asset_rows or asset_rows[track['asset_id']]['kind']!='audio':raise ValueError('Timeline references audio outside this bundle.')
            from .script_audio import migrate as sound_migrate,restore_snapshot,prepare_snapshot
            prepare_snapshot(manifest.get('sound'),mapping,scene_ids,asset_ids,job_ids)
            project=remap(original,mapping);project.update(title=project['title']+' · Restored',mode='hybrid',revision=1,archived=0,created=now(),updated=now())
            config=remap(json.loads(project['settings']),mapping);config.update(paused=True,qa_enabled=False,planning_approved={});project['settings']=encode(config)
            sound_migrate(db)
            from .music_planning import migrate as editing_migrate,restore_snapshot as restore_editing
            editing_migrate(db)
            with db.connect(True) as con:
                def insert(table,row):
                    allowed={r[1] for r in con.execute(f'PRAGMA table_info({table})')}
                    if set(row)-allowed:raise ValueError('Unsupported manifest fields.')
                    columns=list(row);con.execute(f"INSERT INTO {table}({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",tuple(row[c] for c in columns))
                insert('projects',project)
                for table in TABLES:
                    for old in tables[table]:
                        row=remap(old,mapping)
                        for column in ['body','snapshot','dependencies','metadata']:
                            if column in row:row[column]=encode(remap(json.loads(row[column]),mapping))
                        if table=='jobs':
                            row['request_key']='restored:'+row['id'];row['comfy_prompt_id']=None
                            if row['status'] not in ['completed','failed','cancelled','superseded']:
                                row['status']='cancelled';row['error']='Restored history. Work is not resumed automatically.'
                        insert(table,row)
                restore_snapshot(con,manifest.get('sound'),mapping,project_id,insert,remap)
                restore_editing(con,manifest.get('editing'),mapping,project_id,asset_rows,insert,remap)
                timeline=manifest['timeline'];timeline.update(project_id=project_id,revision=1,body=encode(remap(json.loads(timeline['body']),mapping)),updated=now());insert('timelines',timeline)
                con.execute('INSERT OR REPLACE INTO production_state VALUES(?,1,0)',(project_id,))
        except BaseException:
            # Keep failed restore files recoverable; never delete an existing project.
            quarantine=ROOT/'backups'/('failed-restore-'+project_id)
            root.rename(quarantine)
            raise
    db.event('backup.restored',{'project_id':project_id})
    from .media import select_asset
    for scene in db.scenes(project_id):
        for field in ['selected_image_id','selected_video_id']:
            if scene[field]:select_asset(scene[field])
    return db.project(project_id)
