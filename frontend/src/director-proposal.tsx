import {useState} from 'react';
import {proposalSummary} from './proposal-summary';
import type {Project} from './types';
export function DirectorProposal({proposal,project,apply,dismiss}:{proposal:any;project:Project;apply:()=>Promise<any>;dismiss:()=>Promise<any>}){
  const [busy,setBusy]=useState(false);const changes=proposalSummary(proposal,project);const stale=proposal.base_revision!==project.revision;
  return <article className="panel readable-proposal"><span className="badge">Proposed · not applied</span><h3>{proposal.kind==='plan'?'Review your suggested scenes':'Review these changes'}</h3><p>{proposal.body.synopsis||proposal.body.reply}</p>{changes.map((change:any,index:number)=><section key={index}><h4>{change.title}</h4>{change.operation&&<p>This is a requested task. It starts only after you apply this proposal; earlier media remains available.</p>}{change.fields.map((field:any,i:number)=><div className="proposal-diff" key={i}><strong>{field.label}</strong>{field.before!==undefined&&field.before!==''&&<p><span>Current: </span>{String(field.before)}</p>}<p><span>Proposed: </span>{String(field.after)}</p></div>)}</section>)}
    {stale&&<p role="alert">This video changed since the proposal was prepared. Ask the Director for a fresh proposal before applying it.</p>}
    <div className="button-row"><button className="button primary" disabled={busy||stale} onClick={async()=>{setBusy(true);try{await apply()}finally{setBusy(false)}}}>{busy?'Applying…':`Apply ${changes.length||'these'} proposed ${changes.length===1?'change':'changes'}`}</button><button className="button" disabled={busy} onClick={dismiss}>Keep my current version</button></div>
    <details><summary>Technical details</summary><pre>{JSON.stringify(proposal.body,null,2)}</pre></details>
  </article>
}
