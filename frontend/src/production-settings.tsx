import { useEffect,useState } from 'react';
import {useQuery} from '@tanstack/react-query';
import { request } from './api';
import type {Project,Workflow} from './types';

export function ProductionSettings({project,workflows,models,act}:{project:Project;workflows:Workflow[];models:any[];act:any}) {
  const [values,setValues]=useState(project.settings);
  const [dirty,setDirty]=useState(false);const [base,setBase]=useState(project.revision);
  const [brief,setBrief]=useState(project.brief);
  const available=useQuery<any[]>({queryKey:['vision-models'],queryFn:()=>request('/api/language-models'),staleTime:60000});
  const set=(key:string,value:any)=>{setValues(v=>({...v,[key]:value}));setDirty(true)};
  useEffect(()=>{if(!dirty){setValues(project.settings);setBase(project.revision);setBrief(project.brief)}},[project.revision,dirty]);
  return <details className="panel production-settings"><summary>Production settings · models, approvals & creative brief</summary>
    <div className="settings-grid">
      <label>Creative brief<textarea rows={3} value={brief} onChange={e=>{setBrief(e.target.value);setDirty(true)}} /></label>
      <label>Style guide<textarea rows={3} value={values.style_guide || ''} onChange={e=>set('style_guide',e.target.value)}/></label>
      <label>Planning model<select value={values.llm || ''} onChange={e=>set('llm',e.target.value)}><option value="">Select installed model</option>{models.map(m=><option key={m.name}>{m.name}</option>)}</select></label>
      {(['image','video'] as const).map(kind=><label key={kind}>{kind === 'image' ? 'Still-image' : 'Video'} workflow<select value={values[kind+'_workflow']} onChange={e=>set(kind+'_workflow',e.target.value)}>{workflows.filter(w=>kind==='image'?w.task==='text_to_image':w.task==='image_to_video').map(w=><option key={w.id} value={w.id} disabled={w.status!=='ready'}>{w.name}{w.status!=='ready'?' · unavailable':''}</option>)}</select></label>)}
      <label>Still candidates<input type="number" min={1} max={4} value={values.candidates} onChange={e=>set('candidates',Number(e.target.value))}/></label>
      <label>Image steps<input type="number" min={1} max={60} value={values.image_steps} onChange={e=>set('image_steps',Number(e.target.value))}/></label>
      <label>Vision QA model<select value={values.qa_model || ''} onChange={e=>set('qa_model',e.target.value)}><option value="">Select independently from planning model</option><option value="auto">Auto-select an installed vision model</option>{available.data?.filter(m=>m.capabilities.includes('vision')).map(m=><option key={m.name}>{m.name}</option>)}</select></label>
    </div>
    <div className="quality-settings"><label><input type="checkbox" checked={!!values.qa_enabled} onChange={e=>set('qa_enabled',e.target.checked)}/> AI Quality Control — {values.qa_enabled?'On':'Off'}</label><p className="muted">Optional local visual review uses extra memory and time. Manual approval always wins. {available.isError?'Ollama discovery is unavailable; manual review remains available.':''}</p>
      <div className="settings-grid"><label>Rubric<select value={values.qa_rubric||'balanced'} onChange={e=>set('qa_rubric',e.target.value)}>{['lenient','balanced','strict'].map(v=><option key={v}>{v}</option>)}</select></label>
      <label>Still review<select value={values.qa_image_mode||'every'} onChange={e=>set('qa_image_mode',e.target.value)}>{['every','selected','suspicious','off'].map(v=><option key={v}>{v}</option>)}</select></label><label>Video review<select value={values.qa_video_mode||'every'} onChange={e=>set('qa_video_mode',e.target.value)}>{['every','suspicious','off'].map(v=><option key={v}>{v}</option>)}</select></label>
      <label><input type="checkbox" checked={values.qa_auto!==false} onChange={e=>set('qa_auto',e.target.checked)}/> Run checks automatically when enabled</label><label><input type="checkbox" checked={!!values.qa_regenerate} onChange={e=>set('qa_regenerate',e.target.checked)}/> Retry actionable visual failures (maximum two per stage)</label></div>
    </div>
    <p className="muted">Hybrid pauses at the checked reviews. Automatic uses technically valid takes; Manual launches only work you request. An active render keeps its saved inputs.</p>
    <div className="button-row">{['storyboard','prompts','image','video','timeline'].map(g=><label key={g}><input type="checkbox" checked={!!values.gates?.[g]} onChange={e=>set('gates',{...values.gates,[g]:e.target.checked})}/> Review {g}</label>)}</div>
    <div className="button-row"><label><input type="checkbox" checked={!!values.auto_export} onChange={e=>set('auto_export',e.target.checked)}/> Export automatically when reviews are clear</label></div>
    {dirty && base!==project.revision && <p role="alert">The project changed elsewhere. Reload these controls before replacing newer settings.</p>}
    <div className="button-row"><button className="button primary" onClick={()=>act(async()=>{const p=await request(`/api/projects/${project.id}`,{revision:base,brief,settings:values},'PATCH');setValues(p.settings);setBase(p.revision);setDirty(false)},'Production settings saved.')}>Save production settings</button><button className="button" onClick={()=>act(()=>request(`/api/projects/${project.id}/approve-planning`,{}),'Current storyboard and prompts approved.')}>Approve current storyboard & prompts</button></div>
  </details>;
}
