"""Shared release allowlist, immutable file manifest and safe ZIP validation."""
import hashlib,json,re,stat,zipfile
from pathlib import Path,PurePosixPath

ROOT_FILES={'README.md','START_STUDIO.bat','STOP_STUDIO.bat','SETUP_STUDIO.bat','START_TRAY.bat','SceneFlowSetup.exe','release-manifest.json'}
BACKEND_FILES={'run.py','launch.py','provider_worker.py','caption_worker.py','requirements.txt','requirements-lock.txt','bootstrap-lock.txt','studio_tray.ps1','update_package.py','apply_update.py'}

def allowed(value):
    p=PurePosixPath(value)
    if not value or p.is_absolute() or '\\' in value or ':' in value or any(v in {'','.','..','__pycache__'} for v in value.split('/')):return False
    if len(p.parts)==1:return value in ROOT_FILES
    if p.parts[0]=='backend':
        return len(p.parts)==2 and p.name in BACKEND_FILES or len(p.parts)==3 and p.parts[1]=='studio' and (p.suffix=='.py' or p.name=='model_catalog.json') or len(p.parts)==3 and p.parts[1]=='runtime-locks' and p.suffix in {'.txt','.in','.json'}
    if p.parts[0]=='scripts':return len(p.parts)==2 and p.suffix in {'.py','.cs'}
    if p.parts[0]=='docs':return len(p.parts)==2 and p.suffix=='.md'
    if p.parts[0]=='frontend':
        if len(p.parts)==2:return p.name in {'package.json','package-lock.json','vite.config.ts','tsconfig.json','.env.production','index.html'}
        return p.parts[1] in {'dist','src','public'} and p.suffix.lower() in {'.html','.js','.css','.json','.tsx','.ts','.woff2','.txt','.svg','.png','.ico'}
    return False

def safe(root,value):
    if not allowed(value):raise ValueError('The update contains a file outside the application allowlist.')
    root=Path(root).absolute();path=root.joinpath(*PurePosixPath(value).parts)
    current=root
    for part in [None,*path.relative_to(root).parts]:
        if part:current/=part
        if current.exists() or current.is_symlink():
            info=current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:raise ValueError('Linked application folders cannot be updated automatically.')
    if not path.resolve().is_relative_to(root.resolve()):raise ValueError('The update escaped its application folder.')
    return path

def digest(path):
    with Path(path).open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()

def version(value):
    if not re.fullmatch(r'\d+\.\d+\.\d+',value):raise ValueError('Choose a stable numbered Studio release.')
    return tuple(int(v) for v in value.split('.'))

def validate(folder):
    manifest=safe(folder,'release-manifest.json')
    if manifest.stat().st_size>1024**2:raise ValueError('Update file list is too large.')
    value=json.loads(manifest.read_text(encoding='utf-8'));version(value['version'])
    files=value['files']
    if value.get('schema')!=1 or not isinstance(files,list) or not 5<=len(files)<=2000 or len({f['path'].casefold() for f in files})!=len(files):raise ValueError('Unsupported or duplicate update file list.')
    required={'backend/run.py','backend/studio/config.py','backend/bootstrap-lock.txt','frontend/dist/index.html','START_STUDIO.bat','SETUP_STUDIO.bat'}
    if not required<={f['path'] for f in files}:raise ValueError('The update is missing required application files.')
    for item in files:
        path=safe(folder,item['path'])
        if not path.is_file() or path.stat().st_size!=item['bytes'] or digest(path)!=item['sha256']:raise ValueError('An update file failed its checksum.')
    actual={p.relative_to(folder).as_posix() for p in Path(folder).rglob('*') if p.is_file()}
    if actual!={f['path'] for f in files}|{'release-manifest.json'}:raise ValueError('The update contains unlisted files.')
    return value

def extract(archive,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        items=source.infolist();names=set();total=0
        if len(items)>2000:raise ValueError('The update archive has too many files.')
        for item in items:
            name=item.filename
            if item.is_dir():raise ValueError('Use the flat application release archive, without extra folder entries.')
            if name.casefold() in names or item.external_attr>>16&0o170000==0o120000:raise ValueError('The update archive contains duplicate or linked files.')
            names.add(name.casefold());safe(folder,name);total+=item.file_size
            if total>100*1024**2 or item.file_size>30*1024**2:raise ValueError('The update exceeds its supported application size.')
        for item in items:
            path=safe(folder,item.filename);path.parent.mkdir(parents=True,exist_ok=True)
            with source.open(item) as incoming,path.open('wb') as out:
                import shutil
                shutil.copyfileobj(incoming,out,1024**2)
    return validate(folder)
