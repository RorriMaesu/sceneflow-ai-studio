import type {Project} from './types';
export function proposalSummary(proposal:any,project:Project){
  const labels:Record<string,string>={title:'Scene name',summary:'What happens',image_prompt:'Starting picture',video_prompt:'Motion',duration:'Length (seconds)',negative_prompt:'Things to avoid',seed:'Random variation',image_workflow:'Photo tool',video_workflow:'Motion tool'};
  if(proposal.kind==='plan')return (proposal.body.scenes||[]).map((s:any)=>({title:'Add scene: '+s.title,fields:[{label:'What happens',before:'New scene',after:s.summary},{label:'Starting picture',before:'',after:s.image_prompt},{label:'Motion',before:'',after:s.video_prompt}],operation:false}));
  return (proposal.body.actions||[]).map((a:any)=>{
    const scene=project.scenes.find(s=>s.id===a.scene_id);const name=scene?.title||project.title;
    const titles:Record<string,string>={create_scene:'Add a scene',revise_scene:'Change '+name,style_guide:'Change the overall look',regenerate_still:'Create another photo for '+name,regenerate_video:'Create another clip for '+name,review_still:'Ask AI to check the photo in '+name,review_video:'Ask AI to check the clip in '+name,pause_production:'Pause this video',resume_production:'Resume this video'};
    const fields=Object.keys(labels).filter(k=>a[k]!==undefined&&a[k]!==null).map(k=>({label:labels[k],before:k==='title'?scene?.title:scene?.body[k],after:a[k]}));
    if(a.action==='style_guide')fields.push({label:'Overall look',before:project.settings.style_guide,after:a.value});
    return {title:titles[a.action]||'Proposed change',fields,operation:!['create_scene','revise_scene','style_guide'].includes(a.action)};
  });
}
