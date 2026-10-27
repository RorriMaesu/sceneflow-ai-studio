import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request, useConnection } from "./api";
import { readDraft, changed } from "./draft-store";
import type { Project, Job, Asset } from "./types";
export function SaveVideoPage({
  project,
  jobs,
  act,
  go,
  renderMedia,
  busy = false,
}: {
  project: Project;
  jobs: Job[];
  act: any;
  go: (p: string) => void;
  renderMedia: (a: Asset) => React.ReactNode;
  busy?: boolean;
}) {
  const [page, setPage] = useState(1),
    [requested, setRequested] = useState(""),
    [submitting, setSubmitting] = useState(false);
  const history = useQuery<any>({
    queryKey: ["exports", project.id, page],
    queryFn: () => request(`/api/projects/${project.id}/exports?page=${page}`),
    refetchInterval: 4000,
  });
  const hasDraft = () => {
    try {
      const d = readDraft<any>(
        localStorage,
        "timeline." + project.id,
        (v) => Array.isArray(v?.clips) && !!v?.settings,
      );
      return !!d && changed(d.value, d.baseline);
    } catch {
      return false;
    }
  };
  const [draft, setDraft] = useState(hasDraft);
  useEffect(() => {
    const refresh = () => setDraft(hasDraft());
    window.addEventListener("storage", refresh);
    window.addEventListener("sceneflow-draft-changed", refresh);
    return () => {
      window.removeEventListener("storage", refresh);
      window.removeEventListener("sceneflow-draft-changed", refresh);
    };
  }, [project.id]);
  const exports = jobs.filter(
    (j) => j.project_id === project.id && j.kind === "export",
  );
  const active = exports.find((j) =>
    ["queued", "running", "submitted", "reconciling"].includes(j.status),
  );
  const waiting = requested && !exports.some((j) => j.id === requested);
  const canSave =
    !!project.timeline?.clips?.length &&
    !draft &&
    !active &&
    !waiting &&
    !submitting &&
    !busy;
  return (
    <section className="save-video-page">
      <div className="section-heading">
        <div>
          <h2>Save your finished video</h2>
          <p>
            Your saved edit becomes a video file on this computer. Download a
            copy when it is ready.
          </p>
        </div>
      </div>
      {draft ? (
        <div className="draft-warning panel">
          <p>
            Your edit has a protected draft that has not been applied yet. Save
            or discard it in Edit before creating the finished video.
          </p>
          <button className="button primary" onClick={() => go("Timeline")}>
            Return to my edit
          </button>
        </div>
      ) : !project.timeline?.clips?.length ? (
        <div className="panel">
          <p>Arrange your chosen clips before saving a video.</p>
          <button className="button primary" onClick={() => go("Timeline")}>
            Arrange my clips
          </button>
        </div>
      ) : (
        <div className="save-summary">
          <p>
            <strong>Saved edit {project.timeline.revision}</strong> ·{" "}
            {project.timeline.clips.length} clips ·{" "}
            {project.timeline.settings.width} ×{" "}
            {project.timeline.settings.height}
            <br />
            {project.timeline.settings.audio_mode === "silent"
              ? "No sound in this saved edit. Add music or voice in Edit if you want it."
              : "Sound is included according to your saved edit."}
          </p>
          <button
            className="button primary"
            disabled={!canSave}
            onClick={() =>
              act(async () => {
                setSubmitting(true);
                try {
                  const r = await request(
                    `/api/projects/${project.id}/export`,
                    {},
                  );
                  setRequested(r.job_id);
                  history.refetch();
                } finally {
                  setSubmitting(false);
                }
              }, "Finished video requested. It will appear below when ready.")
            }
          >
            {active || waiting || submitting
              ? "Creating your video…"
              : "Create finished video"}
          </button>
        </div>
      )}
      {active && (
        <p role="status">
          {active.status === "queued"
            ? "Your video is waiting for its turn."
            : "Creating the finished file…"}{" "}
          You can leave this page; work continues locally.
        </p>
      )}
      {history.isError && (
        <p role="alert">
          Saved videos could not be refreshed. Check your local connection and
          try again.
        </p>
      )}
      <h3 className="saved-versions-title">Your saved video versions</h3>
      {history.isLoading ? (
        <p>Loading saved videos…</p>
      ) : history.data?.items?.length ? (
        <div className="export-grid">
          {history.data.items.map((a: Asset) => (
            <article className="export-card" key={a.id}>
              {renderMedia(a)}
              <h3>
                {a.metadata.is_editing_preview
                  ? "Editing preview"
                  : a.metadata.partial
                    ? "Partial preview"
                    : "Saved video"}
              </h3>
              <p>
                {a.metadata.timeline_revision === project.timeline.revision
                  ? "Current saved edit"
                  : "Earlier saved edit"}{" "}
                · {Number(a.metadata.duration || 0).toFixed(1)} seconds
              </p>
              <p>
                {new Date(a.created * 1000).toLocaleString()} ·{" "}
                {a.metadata.width} × {a.metadata.height}
              </p>
              <div className="button-row">
                <button
                  className="button primary"
                  onClick={() =>
                    act(async () => {
                      const r = await request(
                        `/api/assets/${a.id}/download-ticket`,
                        {},
                      );
                      const link = document.createElement("a");
                      link.href = useConnection.getState().url + r.url;
                      link.referrerPolicy = "no-referrer";
                      document.body.append(link);
                      link.click();
                      link.remove();
                    }, "Download requested.")
                  }
                >
                  Download MP4
                </button>
                <button
                  className="button"
                  onClick={() =>
                    act(
                      () => request(`/api/assets/${a.id}/reveal`, {}),
                      "Opened the saved video in its folder.",
                    )
                  }
                >
                  Show in folder
                </button>
              </div>
              <details>
                <summary>How this version was made</summary>
                <p>
                  Saved edit {a.metadata.timeline_revision} · {a.metadata.codec}{" "}
                  · {a.metadata.fps} fps. Export size is separate from the
                  original generation size.
                </p>
              </details>
            </article>
          ))}
        </div>
      ) : (
        <p>No saved video yet. Your first finished file will appear here.</p>
      )}
      <div className="button-row history-pager">
        <button
          className="button"
          disabled={page === 1}
          onClick={() => setPage(page - 1)}
        >
          Newer versions
        </button>
        <span>
          Page {page} · {history.data?.total || 0} saved videos
        </span>
        <button
          className="button"
          disabled={!history.data?.has_more}
          onClick={() => setPage(page + 1)}
        >
          Earlier versions
        </button>
      </div>
    </section>
  );
}
