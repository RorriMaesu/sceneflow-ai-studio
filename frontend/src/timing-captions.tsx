import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { request,upload } from './api';
import { readDraft,changed } from './draft-store';
import { useRecoverableDraft,DraftNotice } from './recoverable-draft';
import type { Project,Asset } from './types';

async function downloadCaptions(projectId:string,format:string){
  const value=await request(`/api/projects/${projectId}/captions/text?format=${format}`);
  const url=URL.createObjectURL(new Blob([value.text],{type:'text/plain;charset=utf-8'}));
  const a=document.createElement('a');a.href=url;a.download=value.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
}

function CaptionEditor({projectId,data,act,refresh}:{projectId:string;data:any;act:any;refresh:()=>void}){
  const draft=useRecoverableDraft('captions.'+projectId,{items:data.items,include_mp4:!!data.source.include_mp4},data.revision,v=>Array.isArray(v?.items)&&typeof v?.include_mp4==='boolean');
  const [page,setPage]=useState(0);
  const edit=(index:number,changes:any)=>draft.setValue(v=>({...v,items:v.items.map((c:any,i:number)=>i===index?{...c,...changes}:c)}));
  const adopt=(value:any)=>draft.adopt({items:value.items,include_mp4:!!value.source.include_mp4},value.revision);
  return <><DraftNotice draft={draft}/><p>Check the words and times. Saved captions can be downloaded separately or included as a selectable MP4 caption track.</p>
    <label>Import SRT or VTT subtitles<input type="file" accept=".srt,.vtt" disabled={draft.dirty||draft.conflict} onChange={e=>{const file=e.target.files?.[0];if(file)act(async()=>{if(file.size>1024*1024)throw new Error('Choose a subtitle file up to 1 MB.');const r=await request(`/api/projects/${projectId}/captions/import`,{revision:draft.revision,text:await file.text()});adopt(r);refresh();},'Subtitles imported. Review the words and timing before exporting.');}}/></label>
    {draft.value.items.slice(page*50,page*50+50).map((c:any,i:number)=><div className="setup-tool" key={page*50+i}><div className="form-grid"><label>Starts at (seconds)<input type="number" min="0" step="0.01" value={c.start} onChange={e=>edit(page*50+i,{start:Number(e.target.value)})}/></label><label>Ends at (seconds)<input type="number" min="0" step="0.01" value={c.end} onChange={e=>edit(page*50+i,{end:Number(e.target.value)})}/></label></div><label>Caption text<textarea value={c.text} maxLength={1000} onChange={e=>edit(page*50+i,{text:e.target.value})}/></label><button className="button" onClick={()=>draft.setValue(v=>({...v,items:v.items.filter((_:any,n:number)=>n!==page*50+i)}))}>Remove this caption from the draft</button></div>)}
    {draft.value.items.length>50&&<div className="button-row"><button className="button" disabled={page===0} onClick={()=>setPage(p=>p-1)}>Previous captions</button><span>Page {page+1} of {Math.ceil(draft.value.items.length/50)}</span><button className="button" disabled={(page+1)*50>=draft.value.items.length} onClick={()=>setPage(p=>p+1)}>Next captions</button></div>}
    <button className="button" onClick={()=>draft.setValue(v=>({...v,items:[...v.items,{start:v.items.at(-1)?.end||0,end:(v.items.at(-1)?.end||0)+3,text:'New caption'}]}))}>Add a caption</button>
    <label><input type="checkbox" checked={draft.value.include_mp4} onChange={e=>draft.setValue(v=>({...v,include_mp4:e.target.checked}))}/> Include a selectable caption track when saving the finished video</label>
    <div className="button-row"><button className="button primary" disabled={!draft.dirty||draft.conflict} onClick={()=>act(async()=>{const r=await request(`/api/projects/${projectId}/captions`,{...draft.value,revision:draft.revision});adopt(r);refresh();},'Captions saved. Existing video files stay as they are.')}>Save captions</button><button className="button" disabled={draft.dirty||!data.items.length} onClick={()=>act(()=>downloadCaptions(projectId,'srt'),'Subtitle file downloaded.')}>Download SRT</button><button className="button" disabled={draft.dirty||!data.items.length} onClick={()=>act(()=>downloadCaptions(projectId,'vtt'),'Web caption file downloaded.')}>Download VTT</button></div>
  </>;
}

function SongEditor({project,data,assets,act,refresh,models,goPlanning}:{project:Project;data:any;assets:Asset[];act:any;refresh:()=>void;models:any[];goPlanning:()=>void}){
  const [chosen,setChosen]=useState(''),[replace,setReplace]=useState(false);
  const draft=useRecoverableDraft('song-sections.'+project.id,{items:data.sections.items},data.sections.revision,v=>Array.isArray(v?.items));
  const master=data.master;
  const duration=master?.body.duration||0;
  const model=project.settings.llm||models.find(m=>!m.remote_host)?.name;
  const plan=async(section:any)=>{
    await request(`/api/projects/${project.id}/song/assignment`,{start:section.start,end:section.end,theme:project.brief});
    await request(`/api/projects/${project.id}/plan`,{model,scene_count:Math.max(1,Math.ceil((section.end-section.start)/4)),auto_apply:false,auto_continue:false});
    goPlanning();
  };
  return <details open={project.settings.production_purpose==='music_video'?true:undefined}><summary>Music video · song & sections</summary><p>Lock your original song, then plan pictures around it. Changing visuals does not regenerate or replace the song. A music-video production shares the locked master across its sequences.</p>
    {!master&&<label>Import and lock a song<input type="file" accept=".wav,.mp3,.flac,.ogg,.m4a" onChange={e=>{const file=e.target.files?.[0];if(file)act(async()=>{const r=await upload(`/api/projects/${project.id}/import-media?role=music`,file);await request(`/api/projects/${project.id}/song`,{asset_id:r.asset_id,revision:0});refresh();},'Song imported and locked. Your original file is kept.');}}/></label>}
    {master&&<p><strong>Song locked</strong> · {Number(duration).toFixed(2)} seconds. Save a section to a sequence’s edit or use the full song.</p>}
    <label>{master?'Replace the song (optional)':'Choose your song'}<select value={chosen} onChange={e=>setChosen(e.target.value)}><option value="">Choose an imported or generated recording</option>{assets.filter(a=>a.kind==='audio').map(a=><option key={a.id} value={a.id}>{a.metadata.title||a.metadata.original_name||a.metadata.role||'Recording'} · {Number(a.metadata.duration).toFixed(1)} s</option>)}</select></label>
    {master&&<label><input type="checkbox" checked={replace} onChange={e=>setReplace(e.target.checked)}/> Replace the shared song and reset its section markers. Earlier files are kept.</label>}
    <button className="button" disabled={!chosen||!!master&&!replace} onClick={()=>act(async()=>{await request(`/api/projects/${project.id}/song`,{asset_id:chosen,revision:master?.revision||0,replace});setChosen('');setReplace(false);refresh();},'Song locked. Its original sound stays unchanged.')}>{master?'Replace the locked song':'Lock this song'}</button>
    {master&&<><DraftNotice draft={draft}/><p>Mark the sections you hear, such as intro, verse or chorus. Plan sections up to 160 seconds in one sequence. A plan creates no footage. Fitting trims the visual edit to the song, uses straight cuts and plays once. Add enough visuals first.</p>
      {draft.value.items.map((s:any,i:number)=><div className="setup-tool" key={s.id}><label>Section name<input value={s.label} maxLength={100} onChange={e=>draft.setValue(v=>({...v,items:v.items.map((x:any,n:number)=>n===i?{...x,label:e.target.value}:x)}))}/></label><div className="form-grid">{['start','end'].map(key=><label key={key}>{key==='start'?'Starts':'Ends'} at (seconds)<input type="number" min="0" max={duration} step="0.01" value={s[key]} onChange={e=>draft.setValue(v=>({...v,items:v.items.map((x:any,n:number)=>n===i?{...x,[key]:Number(e.target.value)}:x)}))}/></label>)}</div><button className="button" onClick={()=>draft.setValue(v=>({...v,items:v.items.filter((_:any,n:number)=>n!==i)}))}>Remove section marker</button><button className="button" disabled={draft.dirty} onClick={()=>act(()=>request(`/api/projects/${project.id}/song/place`,{start:s.start,end:s.end,fit_video:true}),'Visuals fitted to the song section. Earlier takes are kept.')}>Fit visuals to this section</button><button className="button" disabled={draft.dirty||!model||s.end-s.start>160} onClick={()=>act(()=>plan(s),"Scene plan queued for this song section. Review it before creating footage.")}>Plan visuals for this section</button></div>)}
      <div className="button-row">{!draft.value.items.length&&<button className="button" onClick={()=>draft.setValue({items:Array.from({length:Math.ceil(duration/30)},(_,i)=>({id:crypto.randomUUID(),label:`Part ${i+1}`,start:i*30,end:Math.min(duration,(i+1)*30)}))})}>Start with 30-second parts</button>}<button className="button" disabled={draft.value.items.length>=200||(draft.value.items.at(-1)?.end||0)>=duration} onClick={()=>draft.setValue(v=>({...v,items:[...v.items,{id:crypto.randomUUID(),label:`Part ${v.items.length+1}`,start:v.items.at(-1)?.end||0,end:Math.min(duration,(v.items.at(-1)?.end||0)+Math.max(1,duration/4))}]}))}>Add a section</button><button className="button primary" disabled={!draft.dirty||draft.conflict} onClick={()=>act(async()=>{const r=await request(`/api/projects/${project.id}/song/sections`,{revision:draft.revision,items:draft.value.items});draft.adopt({items:r.sections.items},r.sections.revision);refresh();},'Song section markers saved.')}>Save section markers</button><button className="button" onClick={()=>act(()=>request(`/api/projects/${project.id}/song/place`,{fit_video:true}),'Visuals fitted to the full song. Earlier takes are kept.')}>Fit visuals to the full song</button></div><p>Face lip-sync and singing mouth animation are not set up on this PC. Song timing, voice-over and captions are available.</p>
    </>}
  </details>;
}

export function TimingCaptions({project,act,goSetup,models,goPlanning}:{project:Project;act:any;goSetup:()=>void;models:any[];goPlanning:()=>void}){
  const cap=useQuery({queryKey:['captions',project.id],queryFn:()=>request(`/api/projects/${project.id}/captions`),refetchInterval:5000});
  const songs=useQuery({queryKey:['song',project.id],queryFn:()=>request(`/api/projects/${project.id}/song`),refetchInterval:10000});
  const tools=useQuery({queryKey:['caption-tools'],queryFn:()=>request('/api/caption-tools'),refetchInterval:10000});
  const assets=useQuery<Asset[]>({queryKey:['caption-assets',project.id],queryFn:()=>request(`/api/assets?project_id=${project.id}`),refetchInterval:5000});
  const [recording,setRecording]=useState(''),[mode,setMode]=useState('transcribe'),[language,setLanguage]=useState('English'),[timing,setTiming]=useState(true);
  const words=useRecoverableDraft('alignment-text.'+project.id,{text:''},0,v=>typeof v?.text==='string');
  const refresh=()=>{cap.refetch();songs.refetch();tools.refetch();};
  const protectCaptionDraft=()=>{const draft=readDraft<any>(localStorage,'captions.'+project.id,v=>Array.isArray(v?.items));if(draft&&changed(draft.value,draft.baseline))throw new Error('Save or discard your caption draft below before using different captions.');};
  const source=assets.data?.find(a=>a.id===recording);
  const isSong=source?.metadata.role==='music'||source?.id===songs.data?.master?.asset_id;
  const actualTiming=!isSong&&(mode==='align'||timing);
  const needsTest=mode==='transcribe'&&!tools.data?.captions_ready || actualTiming&&!tools.data?.alignment_ready;
  if(cap.error||songs.error)return <div role="alert">{cap.error?.message||songs.error?.message}</div>;
  if(!cap.data||!songs.data)return <p role="status">Loading timing & captions…</p>;
  return <section className="panel sound-studio"><h2>Timing & captions</h2><SongEditor key={project.id} project={project} data={songs.data} assets={assets.data||[]} act={act} refresh={refresh} models={models} goPlanning={goPlanning}/>
    <details><summary>Captions · create, review or write your own</summary><p>Use your recorded script, recognize a recording, or add captions yourself. Your recordings stay on this PC.</p>
      <button className="button" onClick={()=>act(async()=>{protectCaptionDraft();await request(`/api/projects/${project.id}/captions/from-script`,{revision:cap.data.revision});refresh();},'Captions made from your recorded script. Review their times below.')}>Use my recorded script</button>
      <details><summary>Recognize speech or lyrics automatically</summary>{!tools.data?.runtime_ready?<p>Automatic captions need program setup. <button className="button" onClick={goSetup}>Open setup</button></p>:<>
        <label>Recording or video<select value={recording} onChange={e=>{setRecording(e.target.value);setMode("transcribe");}}><option value="">Choose a recording with sound</option>{assets.data?.filter(a=>a.metadata.audio_streams===1).map(a=><option key={a.id} value={a.id}>{a.metadata.title||a.metadata.original_name||a.metadata.role||a.kind} · {Number(a.metadata.duration).toFixed(1)} s</option>)}</select></label>
        <label>What do you need?<select value={mode} onChange={e=>setMode(e.target.value)}><option value="transcribe">Recognize the words</option><option value="align" disabled={isSong}>Match words I already know to speech</option></select></label>
        {mode==='align'&&<><DraftNotice draft={words} savedLabel="Enter the exact spoken words below."/><label>Exact spoken words<textarea value={words.value.text} maxLength={6000} onChange={e=>words.setValue({text:e.target.value})}/></label></>}
        <label>Language<select value={language} onChange={e=>setLanguage(e.target.value)}>{mode==='transcribe'&&<option value="">Detect automatically</option>}{['English','Chinese','Cantonese','French','German','Italian','Portuguese','Russian','Spanish'].map(l=><option key={l}>{l}</option>)}</select></label>
        <label><input type="checkbox" checked={actualTiming} disabled={mode==='align'||isSong} onChange={e=>setTiming(e.target.checked)}/> Word timing for supported spoken languages</label>
        <p>{isSong?'Lyrics get rough recognition ranges. Singing word timing requires manual correction.':needsTest?'The first test uses up to 30 seconds. A successful test enables longer recordings, processed in small chunks.':'Long recordings are processed in small chunks; recognition releases its model before word timing starts.'}</p>
        <button className="button primary" disabled={!recording||mode==='align'&&!words.value.text.trim()} onClick={()=>act(()=>request(`/api/projects/${project.id}/captions/recognize`,{asset_id:recording,mode,language:language||null,word_timing:actualTiming,text:words.value.text,test:needsTest}),'Caption work queued. Review the draft here when Activity finishes.')}>{needsTest?'Run a short caption test':'Create a caption draft'}</button>
      </>}</details>
      {cap.data.proposals.map((p:any)=><article className="setup-tool" key={p.id}><h3>Review recognized captions</h3><p>{p.source.note}</p>{p.body.slice(0,50).map((c:any,i:number)=><p key={i}>{c.start.toFixed(2)}–{c.end.toFixed(2)} s · {c.text}</p>)}{p.body.length>50&&<p>{p.body.length} entries in this draft. Use it to review all entries in the editor.</p>}<button className="button" disabled={p.base_revision!==cap.data.revision} onClick={()=>act(async()=>{protectCaptionDraft();await request(`/api/projects/${project.id}/captions/proposals/${p.id}/apply`,{});refresh();},'Caption draft applied. Correct any words or times, then save before exporting.')}>Use this draft</button></article>)}
      <CaptionEditor key={project.id} projectId={project.id} data={cap.data} act={act} refresh={refresh}/>
    </details>
  </section>;
}
