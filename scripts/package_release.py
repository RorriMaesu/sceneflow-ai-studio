"""Package application source and built UI, never private data or model files."""
import argparse,json,re,sys,zipfile
from pathlib import Path

def package(root,output):
    root=Path(root).resolve();sys.path.insert(0,str(root/'backend'))
    from update_package import allowed,digest,validate
    version=re.search(r"^VERSION = ['\"]([^'\"]+)",(root/'backend/studio/config.py').read_text(encoding='utf-8'),re.M)[1]
    if not (root/'frontend/dist/index.html').is_file() or not (root/'SceneFlowSetup.exe').is_file():raise ValueError('Build the interface and Windows setup helper before packaging.')
    paths=[]
    for base in ['backend','frontend/src','frontend/dist','frontend/public','docs','scripts']:
        paths.extend(p for p in (root/base).rglob('*') if p.is_file() and allowed(p.relative_to(root).as_posix()))
    paths.extend(p for p in root.iterdir() if p.is_file() and allowed(p.name) and p.name!='release-manifest.json')
    paths.extend(p for p in (root/'frontend').iterdir() if p.is_file() and allowed(p.relative_to(root).as_posix()))
    paths=sorted(set(paths));manifest={'schema':1,'version':version,'files':[{'path':p.relative_to(root).as_posix(),'bytes':p.stat().st_size,'sha256':digest(p)} for p in paths]}
    output=Path(output);output.mkdir(parents=True,exist_ok=True);archive=output/('SceneFlow-'+version+'-Windows.zip')
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=7) as out:
        for path in paths:out.write(path,path.relative_to(root).as_posix())
        out.writestr('release-manifest.json',json.dumps(manifest,indent=2))
    checksum=digest(archive);archive.with_name(archive.name+'.sha256').write_text(checksum+'  '+archive.name+'\n',encoding='ascii')
    return {'file':str(archive),'bytes':archive.stat().st_size,'sha256':checksum,'files':len(paths)}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args();print(json.dumps(package(args.root,args.output)))
