import { useState } from "react";
import { useRecoverableDraft, DraftNotice } from "./recoverable-draft";
import type { Mode } from "./types";
export interface NewVideoOptions {
  purpose?: 'short'|'series'|'movie'|'music_video';
  title: string;
  brief: string;
  length: number;
  shape: string;
  mode: Mode;
  model: string;
  plan: boolean;
  reference?: File;
}
export function NewVideoWizard({
  close,
  create,
  busy,
  models,
}: {
  close: () => void;
  create: (v: NewVideoOptions) => Promise<any>;
  busy: boolean;
  models: any[];
}) {
  const model = models.find((m) => !m.remote_host)?.name || "";
  const empty = {
    purpose:'short' as const,
    title: "",
    brief: "",
    length: 15,
    shape: "landscape",
    mode: "hybrid" as Mode,
    model,
    plan: true,
  };
  const draft = useRecoverableDraft(
    "new-video",
    empty,
    0,
    (v) =>
      typeof v?.title === "string" &&
      typeof v?.brief === "string" &&
      ["manual", "hybrid", "automatic"].includes(v?.mode),
  );
  const form = draft.value;
  const [reference, setReference] = useState<File>();
  const [error, setError] = useState("");
  const change = (key: string, value: any) =>
    draft.setValue((v) => ({ ...v, [key]: value }));

  return (
    <div className="modal-backdrop">
      <section
        className="modal wide new-video-wizard"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-title"
      >
        <button
          className="modal-close"
          aria-label="Close new project"
          onClick={close}
        >
          ×
        </button>
        <h2 id="new-title">What will you make?</h2>
        <p>
          Describe what you have in mind. You can change everything as you go.
        </p>
        <DraftNotice draft={draft} savedLabel="Nothing has been created yet." />
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (!form.title.trim()) {
              setError("Give your video a name.");
              return;
            }
            const result = await create({
              ...form,
              model: form.model || model,
              title: form.title.trim(),
              reference,
            });
            if (!result) {
              setError(
                "Your video could not be created. Your draft is kept. Close this form to view the problem details, or try again.",
              );
              return;
            }
            if (result) {
              draft.adopt(empty, 0);
              try {
                localStorage.removeItem("sceneflow.safe-draft.new-video");
              } catch {}
              close();
            }
          }}
        >
          <label>What are you making?<select value={form.purpose||'short'} onChange={e=>change('purpose',e.target.value)}><option value="short">Short video</option><option value="series">Show or series</option><option value="movie">Movie</option><option value="music_video">Music video</option></select></label>
          <label>
            Name
            <input
              autoFocus
              required
              maxLength={160}
              value={form.title}
              onChange={(e) => change("title", e.target.value)}
              placeholder="For example: A magical forest at night"
            />
          </label>
          <label>
            What is it about?
            <textarea
              required={(form.purpose||'short')==='short' && form.plan && !!model}
              maxLength={(form.purpose||'short')==='short'?29000:12000}
              rows={3}
              value={form.brief}
              onChange={(e) => change("brief", e.target.value)}
              placeholder="Describe the characters, setting and action in everyday words."
            />
          </label>
          {(form.purpose||'short')==='short' && <><div className="settings-grid">
            <label>
              Approximate length
              <select
                value={form.length}
                onChange={(e) => change("length", Number(e.target.value))}
              >
                <option value={15}>15 seconds · short idea</option>
                <option value={30}>30 seconds · a small story</option>
                <option value={60}>1 minute · more scenes</option>
              </select>
            </label>
            <label>
              Video shape
              <select
                value={form.shape}
                onChange={(e) => change("shape", e.target.value)}
              >
                <option value="landscape">Wide · screens and YouTube</option>
                <option value="portrait">Tall · phone videos</option>
                <option value="square">Square</option>
              </select>
            </label>
          </div>
          <label>
            How would you like to work?
            <select
              value={form.mode}
              onChange={(e) => change("mode", e.target.value)}
            >
              <option value="hybrid">
                Assisted · review as you go (recommended)
              </option>
              <option value="automatic">
                Autopilot · continue automatically after I start
              </option>
              <option value="manual">Manual · I request each task</option>
            </select>
          </label>
          <details>
            <summary>Add a reference picture · optional</summary>
            <label>
              Picture to guide the look
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                onChange={(e) => setReference(e.target.files?.[0])}
              />
            </label>
            <p className="muted">
              Your picture stays local. Re-select it if you close or reload this
              form.
            </p>
          </details>
          <label className="check-label">
            <input
              type="checkbox"
              checked={form.plan && !!model}
              disabled={!model}
              onChange={(e) => change("plan", e.target.checked)}
            />
            Plan my scenes with the local Director
          </label>
          {!model && (
            <p>
              Your story helper is not available yet. You can create the video
              and add scenes yourself.
            </p>
          )}
          <details>
            <summary>Advanced · story helper</summary>
            <label>
              Installed planning model
              <select
                value={form.model}
                onChange={(e) => change("model", e.target.value)}
              >
                {models.map((m) => (
                  <option key={m.name} value={m.name}>
                    {m.name}
                  </option>
                ))}
              </select>
            </label>
          </details>
          </>}
          <p>{(form.purpose||'short')==='short' ? "The length is a planning target. Review the story before creating photos or clips. Add voices and music in Story or Edit." : "Plan your whole production first. Episodes and chapters use the same simple workflow, one manageable sequence at a time. Creating this plan starts no footage or sound."}</p>
          {error && <p role="alert">{error}</p>}
          <button type="submit" className="button primary" disabled={busy}>
            {busy
              ? "Creating your production…"
              : (form.purpose||'short')!=='short' ? "Create production" : form.plan && model
                ? "Create & plan scenes"
                : "Create video"}
          </button>
        </form>
      </section>
    </div>
  );
}
