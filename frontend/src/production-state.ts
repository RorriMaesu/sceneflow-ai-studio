import type {Job,Project} from './types';
export function productionState(project:Project,jobs:Job[],control?:{paused:number|boolean}){
  const scoped=jobs.filter(j=>j.project_id===project.id);
  const active=scoped.find(j=>['running','submitted','reconciling'].includes(j.status));
  if(!control)return {label:'Checking work status…',detail:'Connecting to your local studio.',paused:null,active};
  const paused=!!control.paused;
  if(active){
    const title=project.scenes.find(s=>s.id===active.scene_id)?.title||project.title;
    const task=({image:'Creating a photo',video:'Creating a clip',export:'Saving your video',qa:'Checking a result',director:'Your Director is thinking',plan:'Planning your scenes'} as any)[active.kind]||'Working';
    return {label:paused&&project.mode!=='manual'?'Paused for new automatic work':task,detail:`${paused&&project.mode!=='manual'?task+' · ':''}${title}. ${paused&&project.mode!=='manual'?'The current task can finish.':''}`,paused,active};
  }
  if(scoped.some(j=>j.status==='needs_attention'))return {label:'Needs your attention',detail:'A task needs recovery review before another copy is started. Open Activity.',paused,active};
  if(scoped[0]?.status==='failed')return {label:'A task needs review',detail:'The latest task could not finish. Open Activity to review it; earlier results are safe.',paused,active};
  if(project.mode==='manual')return {label:scoped.some(j=>j.status==='queued')?'Your requested work is waiting':'Manual control',detail:'Only tasks you request will start. Create or review photos and clips in each step.',paused,active};
  if(paused)return {label:'Production paused',detail:'Your finished work is saved. New automatic work waits until you resume.',paused,active};
  if(scoped.some(j=>j.status==='awaiting_review'))return {label:'Waiting for your review',detail:'Review the next scene to continue. Your earlier results are safe.',paused,active};
  if(scoped.some(j=>j.status==='queued'))return {label:'Work is waiting',detail:'Your local studio will start the next task when resources and reviews are ready.',paused,active};
  return {label:'Ready for your next step',detail:'Nothing is running in this video.',paused,active};
}
