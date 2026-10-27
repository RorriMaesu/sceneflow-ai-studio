import {useQuery,useQueryClient} from '@tanstack/react-query';
import {request} from './api';
import {productionState} from './production-state';
import type {Project,Job} from './types';
export function ProjectStatus({project,jobs,act}:{project:Project;jobs:Job[];act:any}){
  const cache=useQueryClient();
  const result=useQuery<any>({queryKey:['performance',project.id],queryFn:()=>request(`/api/projects/${project.id}/performance`),refetchInterval:5000});
  const state=productionState(project,jobs,result.data?.production);
  return <section className="project-status" aria-label="Work status"><div><strong role="status">{state.label}</strong><p>{state.detail}</p>{result.isError&&<p role="alert">Work status could not be refreshed. Reconnect before starting more work.</p>}</div>
    {project.mode!=='manual'&&<button className="button" disabled={state.paused===null||result.isError} onClick={()=>act(async()=>{await request(`/api/projects/${project.id}/${state.paused?'resume':'pause'}`,{});await cache.invalidateQueries({queryKey:['performance',project.id]})},state.paused?'Production resumed.':'New automatic work paused. The current task can finish.')}>{state.paused?'Resume production':'Pause after current task'}</button>}
  </section>
}
