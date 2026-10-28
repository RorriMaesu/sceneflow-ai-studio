import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request, useConnection } from "./api";
import "./setup.css";
import { AppUpdates } from "./app-updates";

const size = (n: number) => n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.ceil(n / 1e6)} MB`;
const labels: Record<string, string> = { models: "Creation tools", cache: "Temporary files", images: "Pictures", videos: "Video clips", music: "Music", speech: "Speech", effects: "Sound effects", exports: "Finished videos", backups: "Backups" };
const states: Record<string, string> = { needs_download: "1 · Download files", needs_runtime: "2 · Finish program setup", needs_test: "3 · Run a sample", setup_required: "Setup required", storage_missing: "Reconnect drive", ready: "Ready on this PC" };

export function StudioSetup({ act, done }: { act: any; done?: () => void }) {
  const query = useQuery({ queryKey: ["studio-setup"], queryFn: () => request("/api/setup"), refetchInterval: 3000 });
  const [busy, setBusy] = useState(false);
  const [toolQuote,setToolQuote]=useState<any>();
  const [quote, setQuote] = useState<any>();
  const [runtimeQuote, setRuntimeQuote] = useState<any>();
  const [sample, setSample] = useState("");
  const [updates, setUpdates] = useState<any[]>();
  const [selectedRoot, setSelectedRoot] = useState("");
  const data = query.data;
  useEffect(() => { if (quote || runtimeQuote || toolQuote) { const review = document.getElementById("download-review"); review?.scrollIntoView({ block: "start" }); review?.focus({ preventScroll: true }); } }, [quote, runtimeQuote,toolQuote]);
  async function run(action: () => Promise<any>, message = "Setup updated.") {
    if (busy) return;
    setBusy(true);
    try { return await act(async () => { const value = await action(); await query.refetch(); return value; }, message); }
    finally { setBusy(false); }
  }
  if (query.error) return <div className="error-banner" role="alert">{query.error.message} <button onClick={() => query.refetch()}>Try again</button></div>;
  if (!data) return <p role="status">Checking your studio…</p>;
  const storage = data.storage;
  const roots = storage.roots;
  const defaultRoot = roots.find((r: any) => r.id === storage.routes.models);
  const hasFolders = Object.keys(storage.routes).length > 0;
  const active = data.downloads.filter((d: any) => ["queued", "downloading", "verifying", "paused", "failed"].includes(d.status));
  return <section className="studio-setup">
    <h2>Set up your studio</h2>
    <p>Choose where your work goes, then add only the tools you need. Your existing videos stay available.</p>
    <section className="panel settings-panel">
      <h3>1. Choose your folders</h3>
      <p>{hasFolders ? "Your new files will use the folders below." : "Recommended folders keep large files with this Studio installation."} Existing files keep their current locations.</p>
      <div className="button-row">
        <button className="button primary" disabled={busy || hasFolders} onClick={() => run(() => request("/api/setup/folders/recommended", {}), "Recommended folders are ready.")}>{hasFolders ? "Folders selected" : "Use recommended folders"}</button>
        <button className="button" disabled={busy} onClick={() => run(async () => {
          const value = await request("/api/setup/folders/choose", {});
          if (value.root) setSelectedRoot(value.root.id);
          return value;
        }, "Folder chooser closed.")}>Choose another folder…</button>
      </div>
      {selectedRoot && <div className="setup-folder-choice">
        <p>Selected: {roots.find((r: any) => r.id === selectedRoot)?.path || "Your chosen folder"}</p>
        <button className="button" disabled={busy} onClick={() => run(async () => {
          const result = await request("/api/setup/folders/routes", { routes: Object.fromEntries(storage.roles.map((role: string) => [role, selectedRoot])) });
          setSelectedRoot(""); return result;
        }, "New files will use your chosen folder.")}>Use for all new files</button>
      </div>}
      {defaultRoot && <p><strong>{defaultRoot.path}</strong> · {defaultRoot.available ? `${size(defaultRoot.free_bytes)} free` : "Drive missing — reconnect it"}</p>}
      <details><summary>Choose separate folders for pictures, voices, videos and more</summary>
        {storage.roles.map((role: string) => <label key={role}>{labels[role] || role}
          <select value={storage.routes[role] || ""} disabled={busy} onChange={(event) => run(() => request("/api/setup/folders/routes", { routes: { [role]: event.target.value } }), `${labels[role]} folder saved.`)}>
            <option value="" disabled>Choose a folder</option>
            {roots.map((r: any) => <option key={r.id} value={r.id} disabled={!r.available}>{r.path}{!r.available ? " (missing drive)" : ""}</option>)}
          </select>
        </label>)}
        <p>Use “Choose another folder” to add a location. Folder choices apply to new files.</p>
      </details>
    </section>
    <section className="panel settings-panel">
      <h3>2. Check your existing tools</h3>
      <p>Pictures & motion: <strong>{data.services.comfy.connected ? "Connected" : "Start the local video service"}</strong></p>
      <p>Story helper: <strong>{data.services.ollama.connected ? "Connected" : "Start the local story helper"}</strong></p>
      <p>New tools are marked Ready only after a sample succeeds on this computer. {data.memory_manager?.policy || "Graphics-heavy tasks share one work queue"}.</p>
      {data.memory_manager?.active && <p role="status">A creation task is using the graphics card. Other requests will wait for a safe turn.</p>}
    </section>
    <details className="panel settings-panel">
      <summary>3. Add voices, music and other tools (optional)</summary>
      <p>You can finish setup using your existing tools. Speech, music and other additions are optional.</p>
      <div className="setup-tools">
        {data.packs.map((p: any) => <article className="setup-tool" key={p.id}>
          <div><h4>{p.name}</h4><span className="badge">{states[p.state] || p.state}</span></div>
          <p>{p.reason}</p>
          <div className="button-row">
            {['voices-small','music','effects','captions','alignment'].includes(p.id)&&p.state!=='ready'&&<button className="button primary" disabled={busy||!hasFolders||data.tool_setups?.some((j:any)=>j.pack_id===p.id&&['queued','downloading','programs','testing'].includes(j.status))} onClick={()=>run(async()=>{setQuote(undefined);setRuntimeQuote(undefined);setToolQuote(await request(`/api/setup/tools/${p.id}/quote`,{}));},'Complete setup size and folders checked.')}>Set up {p.name.toLowerCase()}</button>}
            {!p.installed && !["voices-small","music","effects","captions","alignment"].includes(p.id) && <button className="button" disabled={busy || !hasFolders || ["setup_required", "storage_missing"].includes(p.state)} onClick={() => run(async () => { setRuntimeQuote(undefined);setQuote(await request(`/api/setup/packs/${p.id}/quote`, {})); }, "Download size and folder checked.")}>{p.bytes ? `Review ${size(p.bytes)} download` : "Setup required"}</button>}
            {p.state === "needs_runtime" && !["voices-small","music","effects","captions","alignment"].includes(p.id) && <button className="button primary" disabled={busy || data.runtime_jobs?.some((j:any)=>["queued","installing"].includes(j.status))} onClick={() => run(async () => { setQuote(undefined);setRuntimeQuote(await request(`/api/setup/packs/${p.id}/runtime-quote`, {})); }, "Program setup checked.")}>Finish program setup</button>}
            {["needs_test","ready"].includes(p.state) && ["voices-small","music","effects"].includes(p.id) && <button className="button" disabled={busy} onClick={() => run(() => request(`/api/setup/packs/${p.id}/sample`, {}), "Sample queued. You can keep using your studio while it runs.")}>{p.state === "ready" ? "Run another sample" : "Run a short sample"}</button>}
            {p.state === "ready" && ['music','effects'].includes(p.id) && <button className="button" disabled={busy} onClick={()=>run(()=>request(`/api/setup/packs/${p.id}/sample`,{seconds:p.id==='music'?180:10}),"Longer sample queued. Current limits stay in place until it passes.")}>Test {p.id==='music'?'180':'10'}-second cues</button>}
            {p.state === 'ready' && p.id === 'music' && <button className="button" disabled={busy} onClick={()=>run(()=>request('/api/setup/packs/music/sample',{vocal:true,seconds:180}),"Singing sample queued. Listen to the result before using vocals.")}>Test a 3-minute song</button>}
            {data.samples?.[p.id]?.asset_id && <button className="button" onClick={()=>run(async()=>{const v=await request(`/api/assets/${data.samples[p.id].asset_id}/ticket`,{});setSample(useConnection.getState().url+v.url);},"Sample ready to listen.")}>Listen to sample</button>}
            {data.samples?.[p.id]?.elapsed_seconds && <p>Last sample took about {Math.max(1,Math.ceil(data.samples[p.id].elapsed_seconds/60))} minute(s), including loading the tool.</p>}
            {p.id==='music'&&data.samples?.music?.tested_lengths&&<p>Tested lengths: instrumental {data.samples.music.tested_lengths.instrumental||0} s · singing {data.samples.music.tested_lengths.vocal||0} s.</p>}
            <details><summary>Tool details & repair</summary>{['voices-small','music','effects','captions','alignment'].includes(p.id)&&<button className="button" disabled={busy||!hasFolders} onClick={()=>run(async()=>{setQuote(undefined);setRuntimeQuote(undefined);setToolQuote(await request(`/api/setup/tools/${p.id}/quote`,{}));},'Repair checked. Verified existing files will be reused.')}>Review repair setup</button>}<p>{p.repo} · {p.license}</p><p>Version: {p.revision.slice(0, 12)}</p><a href={p.source} target="_blank" rel="noreferrer">Official source</a></details>
          </div>
        </article>)}
      </div>
      {!hasFolders && <p>Choose your folders above before reviewing a download.</p>}
    </details>
    {toolQuote&&<section className="panel settings-panel" id="download-review" tabIndex={-1} aria-label="Review complete tool setup"><h3>Install this tool and check it works</h3><p>Up to <strong>{size(toolQuote.download_bytes_upper)}</strong> to download, including model and private program files. Verified cached files can reduce this.</p>{toolQuote.models.map((m:any)=><p key={m.pack_id}>Save model files to: {m.destination}<br/>License: {m.license} · <a href={m.source} target="_blank" rel="noreferrer">Official terms</a></p>)}{toolQuote.program&&<p>Private program folder: {toolQuote.program.destination}</p>}{Object.entries(toolQuote.working_bytes_by_volume).map(([volume,bytes])=><p key={volume}>{volume}: allow {size(Number(bytes))} of working space, plus the storage reserve.</p>)}<p>{toolQuote.note}</p><div className="button-row"><button className="button primary" disabled={busy} onClick={()=>run(async()=>{await request('/api/setup/tools',{quote_id:toolQuote.id,confirm:true});setToolQuote(undefined);},'Setup started. SceneFlow will download, verify, install and create the sample in order.')}>{toolQuote.automatic_sample?'Install and test':'Install caption tools'}</button><button className="button" disabled={busy} onClick={()=>setToolQuote(undefined)}>Not now</button></div></section>}
    {data.tool_setups?.filter((t:any)=>t.status!=='ready').map((t:any)=><section className="panel settings-panel" key={t.id}><h3>{data.packs.find((p:any)=>p.id===t.pack_id)?.name||'Tool'} setup</h3><p role="status">{t.step}</p>{t.error&&<p role="alert">{t.error}</p>}{['paused','failed'].includes(t.status)&&<button className="button" disabled={busy} onClick={()=>run(()=>request(`/api/setup/tools/${t.id}/continue`,{}),'Setup continued from saved files.')}>Continue setup</button>}{['queued','downloading','programs','testing'].includes(t.status)&&<button className="button" disabled={busy} onClick={()=>run(()=>request(`/api/setup/tools/${t.id}/pause`,{}),'Setup will pause after its current step.')}>Pause setup</button>}</section>)}
    {sample && <div className="panel"><p>Listen before using this tool in your story.</p><audio src={sample} controls /></div>}
    {runtimeQuote && <section className="panel settings-panel" id="download-review" tabIndex={-1} aria-label="Review program setup"><h3>Finish this tool’s program setup</h3><p>Up to <strong>{size(runtimeQuote.download_bytes_upper)}</strong> to download. Allow 12 GB of free working space for this step. Shared files can reduce the download.</p><p>Save to: {runtimeQuote.destination}</p><p>{runtimeQuote.note}</p><div className="button-row"><button className="button primary" disabled={busy} onClick={()=>run(async()=>{const r=await request('/api/setup/runtimes',{quote_id:runtimeQuote.id,confirm:true});setRuntimeQuote(undefined);return r;},"Program setup queued.")}>Set up this tool</button><button className="button" disabled={busy} onClick={()=>setRuntimeQuote(undefined)}>Not now</button></div></section>}
    {data.runtime_jobs?.filter((j:any)=>j.status!=="completed").map((j:any)=><section className="panel settings-panel" key={j.id}><h3>{j.runtime_id === "speech" ? "Voices" : j.runtime_id === "music" ? "Music" : j.runtime_id === "captions" ? "Captions" : "Sound effects"} program setup</h3><p role="status">{j.step}</p>{j.error && <p role="alert">{j.error}</p>}{j.status === "failed" && <p>Choose “Finish program setup” above to retry using the saved download cache.</p>}</section>)}
    {quote && <section className="panel settings-panel" id="download-review" tabIndex={-1} aria-label="Review download">
      <h3>Review this download</h3>
      <p><strong>{size(quote.download_bytes)}</strong> to download · {size(quote.pack_bytes)} installed files</p>
      <p>Save to: {quote.destination}</p><p>License: {quote.license}. <a href={quote.source} target="_blank" rel="noreferrer">Read the official model terms</a></p>
      <p>{quote.note} No photo or video generation starts with this download.</p>
      {quote.files.some((f: any) => f.runtime_code) && <p>This pack includes pinned model support code. Downloading it does not run it; runtime setup is a separate step.</p>}
      <div className="button-row"><button className="button primary" disabled={busy} onClick={() => run(async () => { const result = await request("/api/setup/downloads", { quote_id: quote.id, confirm: true }); setQuote(undefined); return result; }, "Download queued. You can keep using your studio.")}>Download these files</button><button className="button" disabled={busy} onClick={() => setQuote(undefined)}>Not now</button></div>
    </section>}
    {active.length > 0 && <section className="panel settings-panel"><h3>Downloads</h3>{active.map((d: any) => <article className="setup-tool" key={d.id}>
      <strong>{data.packs.find((p: any) => p.id === d.pack_id)?.name || d.pack_id}</strong>
      <p>{d.status} · {size(d.bytes_done)} of {size(d.bytes_total)}</p>
      <progress value={d.bytes_done} max={d.bytes_total} aria-label="Download progress" />
      {d.error && <p role="status">{d.error}</p>}
      <button className="button" disabled={busy} onClick={() => run(() => request(`/api/setup/downloads/${d.id}/${["paused", "failed"].includes(d.status) ? "resume" : "pause"}`, {}), "Download updated.")}>{["paused", "failed"].includes(d.status) ? "Resume download" : "Pause download"}</button>
    </article>)}</section>}
    <AppUpdates act={act}/>
    <details className="panel settings-panel"><summary>Creation model updates</summary>
      <p>Check for newer tools without replacing the versions used by your existing work.</p>
      <button className="button" disabled={busy} onClick={() => run(async () => setUpdates(await request("/api/setup/updates/check", {})), "Update check complete. Your tools were not changed.")}>Check for updates</button>
      {updates && updates.map((u: any) => <p key={u.pack_id}>{data.packs.find((p: any) => p.id === u.pack_id)?.name}: {u.error || (u.update_available ? "New version found — compatibility testing required before use." : "Catalog version is current.")}</p>)}
    </details>
    <button className="button primary" disabled={busy || !hasFolders} onClick={() => run(async () => { const result = await request("/api/setup/finish", {}); done?.(); return result; }, "Setup saved. You can add or repair creation tools whenever you need them.")}>{data.setup_complete ? "Save setup choices" : "Finish setup with existing tools"}</button>
  </section>;
}
