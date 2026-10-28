"""Owned, journaled application replacement with source-only rollback."""
import argparse,json,os,shutil,sqlite3,subprocess,sys,time,uuid
from pathlib import Path
from update_package import safe,validate,digest

def save(path,value):
    temporary=path.with_suffix('.part');temporary.write_text(json.dumps(value,indent=2),encoding='utf-8');os.replace(temporary,path)

def copy(source,target):
    target.parent.mkdir(parents=True,exist_ok=True);part=target.with_name(target.name+'.'+uuid.uuid4().hex+'.update-part');shutil.copy2(source,part);os.replace(part,target)

def rollback(root,plan):
    backup=Path(plan['backup'])
    for item in reversed(plan.get('journal',[])):
        target=safe(root,item['path'])
        if item['existed']:
            original=safe(backup/'files',item['path'])
            if digest(original)!=item['old_sha256']:raise ValueError('The update backup changed. Source rollback stopped safely.')
            copy(original,target)
        else:target.unlink(missing_ok=True)

def apply(root,plan,probe=None):
    root=Path(root);path=root/'local'/'app-update.json';stage=Path(plan['stage']);value=validate(stage)
    if value['version']!=plan['version'] or digest(stage/'release-manifest.json')!=plan['manifest_sha256']:raise ValueError('The staged update changed. Prepare it again.')
    if digest(stage/'backend/bootstrap-lock.txt')!=digest(root/'backend/bootstrap-lock.txt'):raise ValueError('This release changes Studio program dependencies. Use a separately reviewed Windows app setup instead.')
    backup=Path(plan['backup']);backup.mkdir(parents=True,exist_ok=True)
    database=root/'database'/'studio.sqlite3'
    if database.exists():
        with sqlite3.connect(database) as source,sqlite3.connect(backup/'studio.sqlite3') as destination:source.backup(destination)
    plan.update(state='applying',journal=[]);save(path,plan)
    try:
        for item in value['files']:
            target=safe(root,item['path']);existed=target.exists()
            if existed and digest(target)==item['sha256']:continue
            row={'path':item['path'],'existed':existed,'old_sha256':digest(target) if existed else None}
            if existed:copy(target,safe(backup/'files',item['path']))
            plan['journal'].append(row);save(path,plan)
            copy(safe(stage,item['path']),target)
        plan['state']='checking';save(path,plan)
        if probe:probe(root,plan)
        else:
            env={**os.environ,'STUDIO_ROOT':str(backup/'probe-data'),'STUDIO_PORT':'8789','PYTHONDONTWRITEBYTECODE':'1'}
            code="import sys;sys.path.insert(0,"+repr(str(root/'backend'))+");from studio.app import app;assert app.version=="+repr(plan['version'])
            result=subprocess.run([sys.executable,'-I','-c',code],cwd=root,env=env,capture_output=True,timeout=90)
            if result.returncode:raise ValueError('The new application did not pass its startup check.')
        plan['state']='applied';plan['error']=None;save(path,plan)
    except BaseException as error:
        plan['state']='rolling_back';plan['error']=str(error);save(path,plan)
        rollback(root,plan);plan['state']='rolled_back';save(path,plan)
        raise

def launch(root):
    log=Path(root)/'logs'/'app-update-launch.log';log.parent.mkdir(parents=True,exist_ok=True)
    with log.open('ab') as output:
        process=subprocess.Popen([sys.executable,str(Path(root)/'backend/launch.py'),'--quiet','--no-browser'],cwd=root,stdout=output,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,creationflags=0x08000000 if os.name=='nt' else 0)
        if process.wait(timeout=90):raise ValueError('Studio did not reopen after this application update.')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',required=True);parser.add_argument('--recover',action='store_true');parser.add_argument('--rollback',action='store_true');args=parser.parse_args()
    root=Path(args.root).resolve();path=root/'local'/'app-update.json'
    if not path.exists():return
    lock=(root/'local'/'app-update.lock').open('a+b')
    if os.name=='nt':
        import msvcrt
        lock.seek(0)
        if not lock.read(1):lock.write(b'0');lock.flush()
        lock.seek(0)
        try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:raise ValueError('An application update is already running. Wait for Studio to reopen.')
    else:
        import fcntl
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    plan=json.loads(path.read_text(encoding='utf-8'))
    if plan['root']!=str(root):raise ValueError('Update belongs to another installation.')
    if args.recover:
        if plan['state'] in {'applying','checking','rolling_back','rollback_scheduled'}:
            rollback(root,plan);plan['state']='rolled_back';plan['error']='Interrupted update was restored before Studio opened.';save(path,plan)
        elif plan['state']=='scheduled':
            plan['state']='prepared';plan.pop('parent',None);save(path,plan)
        return
    parent=plan.get('parent')
    if parent:
        import psutil
        for _ in range(120):
            try:
                process=psutil.Process(parent['pid'])
                if abs(process.create_time()-parent['created'])>=.01:break
            except psutil.NoSuchProcess:break
            time.sleep(.5)
        else:raise ValueError('The owned Studio service did not stop; no update files were changed.')
    try:
        if args.rollback:
            rollback(root,plan);plan['state']='rolled_back';save(path,plan)
        else:apply(root,plan)
    except Exception as error:
        print(str(error),flush=True)
    try:launch(root)
    except Exception:
        if plan['state']=='applied':
            rollback(root,plan);plan['state']='rolled_back';plan['error']='The updated app could not reopen; the previous files were restored.';save(path,plan);launch(root)
        else:raise

if __name__=='__main__':main()
