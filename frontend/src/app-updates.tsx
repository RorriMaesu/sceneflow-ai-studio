import {useState,useEffect} from 'react';
import {useQuery} from '@tanstack/react-query';
import {request,useConnection} from './api';

export function AppUpdates({act}:{act:any}){
  const query=useQuery({queryKey:['app-updates'],queryFn:()=>request('/api/app-updates'),refetchInterval:10000});
  const [review,setReview]=useState<any>(),[prepared,setPrepared]=useState<any>(),[confirmed,setConfirmed]=useState(false),[restarting,setRestarting]=useState(false),[message,setMessage]=useState('');
  useEffect(()=>{
    if(!restarting)return;
    let stopped=false;let attempts=0;
    const timer=setInterval(async()=>{
      if(++attempts>90){setRestarting(false);setMessage('Open START_STUDIO to recover or reopen your Studio. Saved projects are kept.');return;}
      try{
        const status=await request('/api/app-updates');
        if(!stopped&&status.update?.state==='applied'&&status.installed===status.update.version)location.reload();
        if(!stopped&&status.update?.state==='rolled_back'){setRestarting(false);setMessage(status.update.error||'Previous application restored. Your projects and models are kept.');query.refetch();}
      }catch{/* A brief disconnect is expected while the owned service restarts. */}
    },2000);
    return()=>{stopped=true;clearInterval(timer);};
  },[restarting]);
  const data=query.data;const plan=data?.update;const ready=prepared||plan?.state==='prepared';
  return <details className="panel settings-panel"><summary>Application updates</summary><p>Installed: {data?.installed||'checking'}. Check first, prepare a verified copy, then restart when your work is idle. Your projects, recordings, models and pairing stay local.</p>{query.error&&!restarting&&<p role="alert">{query.error.message}</p>}<button className="button" disabled={restarting} onClick={()=>act(async()=>{setReview(await request('/api/app-updates/check',{}));setConfirmed(false);},'Application update check complete.')}>Check application updates</button>{review&&!review.available&&<p role="status">{review.message}</p>}{review?.available&&<><p>Version {review.version} · {(review.bytes/1e6).toFixed(1)} MB · <a href={review.release_url} target="_blank" rel="noreferrer">Release notes</a></p><p>{review.notes}</p><button className="button" disabled={restarting} onClick={()=>act(async()=>{setPrepared(await request('/api/app-updates/stage',{quote_id:review.quote_id}));query.refetch();},'Update downloaded and verified. Review the restart below.')}>Prepare this update</button></>}{ready&&!restarting&&<><p>Verified update ready. Finish or stop queued work before restarting.</p><label><input type="checkbox" checked={confirmed} onChange={e=>setConfirmed(e.target.checked)}/> Save my work, update the application and reopen Studio.</label><button className="button primary" disabled={!confirmed} onClick={()=>act(async()=>{const r=await request('/api/app-updates/apply',{confirm:true});setMessage(r.message);setRestarting(true);},'Studio is reopening after its update.')}>Update and reopen Studio</button></>}{plan?.state==='applied'&&!restarting&&<details><summary>Restore the previous application</summary><p>This restores application files and keeps your current productions and models. A database snapshot is retained in the update backup for advanced recovery.</p><button className="button" onClick={()=>act(async()=>{const r=await request('/api/app-updates/rollback',{confirm:true});setMessage(r.message);setRestarting(true);},'Restoring the previous application.')}>Restore version {plan.old_version}</button></details>}{(message||restarting)&&<p role="status">{message||'Studio is reopening…'}</p>}{restarting&&<a href={useConnection.getState().url}>Open the local Studio after restart</a>}</details>;
}
