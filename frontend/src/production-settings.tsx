import { useState } from 'react';
import { request } from './api';
import type {Project,Workflow} from './types';

export function ProductionSettings({project,workflows,models,act}:{project:Project;workflows:Workflow[];models:any[];act:any}) {
  const [values,setValues]=useState(project.settings);
  const set=(key:string,value:any)=>setValues(v=>({...v,[key]:value}));
  return <details className="panel production-settings"><summary>Production settings · models, approvals & creative brief</summary>
    <div className="settings-grid">
      <label>Creative brief<textarea rows={3} defaultValue={project.brief} id={`brief-${project.id}`} /></label>
      <label>Style guide<textarea rows={3} value={values.style_guide || ''} onChange={e=>set('style_guide',e.target.value)}/></label>
      <label>Planning model<select value={values.llm || ''} onChange={e=>set('llm',e.target.value)}><option value="">Select installed model</option>{models.map(m=><option key={m.name}>{m.name}</option>)}</select></label>
      {(['image','video'] as const).map(kind=><label key={kind}>{kind === 'image' ? 'Still-image' : 'Video'} workflow<select value={values[kind+'_workflow']} onChange={e=>set(kind+'_workflow',e.target.value)}>{workflows.filter(w=>kind==='image'?w.task==='text_to_image':w.task==='image_to_video').map(w=><option key={w.id} value={w.id} disabled={w.status!=='ready'}>{w.name}{w.status!=='ready'?' · unavailable':''}</option>)}</select></label>)}
      <label>Still candidates<input type="number" min={1} max={4} value={values.candidates} onChange={e=>set('candidates',Number(e.target.value))}/></label>
      <label>Image steps<input type="number" min={1} max={60} value={values.image_steps} onChange={e=>set('image_steps',Number(e.target.value))}/></label>
      <label>Vision QA model<select value={values.qa_model || ''} onChange={e=>set('qa_model',e.target.value)}><option value="">Select independently from planning model</option>{models.map(m=><option key={m.name}>{m.name}</option>)}</select></label>
    </div>
    <p className="muted">Hybrid pauses at the checked reviews. Automatic uses technically valid takes; Manual launches only work you request. An active render keeps its saved inputs.</p>
    <div className="button-row">{['storyboard','prompts','image','video','timeline'].map(g=><label key={g}><input type="checkbox" checked={!!values.gates?.[g]} onChange={e=>set('gates',{...values.gates,[g]:e.target.checked})}/> Review {g}</label>)}</div>
    <div className="button-row"><label><input type="checkbox" checked={!!values.auto_export} onChange={e=>set('auto_export',e.target.checked)}/> Export automatically when reviews are clear</label></div>
    <div className="button-row"><button className="button primary" onClick={()=>act(()=>request(`/api/projects/${project.id}`,{revision:project.revision,brief:(document.getElementById(`brief-${project.id}`) as HTMLTextAreaElement).value,settings:values},'PATCH'),'Production settings saved.')}>Save production settings</button><button className="button" onClick={()=>act(()=>request(`/api/projects/${project.id}/approve-planning`,{}),'Current storyboard and prompts approved.')}>Approve current storyboard & prompts</button></div>
  </details>;
}
