import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request } from "./api";
import "./setup.css";

const size = (n: number) => n >= 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${Math.ceil(n / 1e6)} MB`;
const labels: Record<string, string> = { models: "Creation tools", cache: "Temporary files", images: "Pictures", videos: "Video clips", music: "Music", speech: "Speech", effects: "Sound effects", exports: "Finished videos", backups: "Backups" };
const states: Record<string, string> = { needs_download: "Needs download", needs_test: "Needs a sample test", setup_required: "Setup required", storage_missing: "Reconnect drive", ready: "Ready on this PC" };

export function StudioSetup({ act, done }: { act: any; done?: () => void }) {
  const query = useQuery({ queryKey: ["studio-setup"], queryFn: () => request("/api/setup"), refetchInterval: 3000 });
  const [busy, setBusy] = useState(false);
  const [quote, setQuote] = useState<any>();
  const [updates, setUpdates] = useState<any[]>();
  const [selectedRoot, setSelectedRoot] = useState("");
  const data = query.data;
  useEffect(() => { if (quote) { const review = document.getElementById("download-review"); review?.scrollIntoView({ block: "start" }); review?.focus({ preventScroll: true }); } }, [quote]);
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
            <button className="button" disabled={busy || !hasFolders || ["setup_required", "storage_missing", "ready"].includes(p.state) || p.installed} onClick={() => run(async () => setQuote(await request(`/api/setup/packs/${p.id}/quote`, {})), "Download size and folder checked.")}>{p.installed ? "Files downloaded" : p.bytes ? `Review ${size(p.bytes)} download` : "Setup required"}</button>
            <details><summary>Tool details</summary><p>{p.repo} · {p.license}</p><p>Version: {p.revision.slice(0, 12)}</p><a href={p.source} target="_blank" rel="noreferrer">Official source</a></details>
          </div>
        </article>)}
      </div>
      {!hasFolders && <p>Choose your folders above before reviewing a download.</p>}
    </details>
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
    <details className="panel settings-panel"><summary>Updates</summary>
      <p>Check for newer tools without replacing the versions used by your existing work.</p>
      <button className="button" disabled={busy} onClick={() => run(async () => setUpdates(await request("/api/setup/updates/check", {})), "Update check complete. Your tools were not changed.")}>Check for updates</button>
      {updates && updates.map((u: any) => <p key={u.pack_id}>{data.packs.find((p: any) => p.id === u.pack_id)?.name}: {u.error || (u.update_available ? "New version found — compatibility testing required before use." : "Catalog version is current.")}</p>)}
    </details>
    <button className="button primary" disabled={busy || !hasFolders} onClick={() => run(async () => { const result = await request("/api/setup/finish", {}); done?.(); return result; }, "Setup saved. You can add or repair creation tools whenever you need them.")}>{data.setup_complete ? "Save setup choices" : "Finish setup with existing tools"}</button>
  </section>;
}
