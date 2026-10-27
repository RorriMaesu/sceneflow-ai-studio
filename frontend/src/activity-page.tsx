import { useState } from "react";
import { request } from "./api";
import type { Project, Job } from "./types";
const status: Record<string, string> = {
  completed: "Done",
  failed: "Needs review",
  queued: "Waiting",
  running: "Working",
  submitted: "Creating",
  reconciling: "Checking the connection",
  awaiting_review: "Waiting for your review",
  cancelled: "Stopped",
  superseded: "Replaced by a newer request",
  needs_attention: "Needs recovery review",
};
const kinds: Record<string, string> = {
  image: "Photo creation",
  video: "Clip creation",
  plan: "Scene planning",
  director: "Director request",
  qa: "AI quality check",
  export: "Save video",
  speech: "Speech creation",
  music: "Music creation",
  effects: "Sound effect creation",
  outline: "Season or chapter planning",
};
export function ActivityPage({
  projects,
  jobs,
  act,
  choose,
  goSetup,
  openProduction,
}: {
  projects: Project[];
  jobs: Job[];
  act: any;
  active?: string;
  choose: (id: string) => void;
  goSetup?: () => void;
  openProduction?: (id:string) => void;
}) {
  const [scope, setScope] = useState("all"),
    [showDone, setShowDone] = useState(false),
    [reviewed, setReviewed] = useState<Record<string, boolean>>({});
  const scoped = jobs.filter((j) => scope === "all" || j.project_id === scope);
  const shown = scoped.filter(
    (j) =>
      showDone || !["completed", "cancelled", "superseded"].includes(j.status),
  );
  return (
    <section>
      <h1>Activity</h1>
      <p>See what is working, waiting, or ready for your review.</p>
      <div className="activity-filters">
        <label>
          Show activity for
          <select value={scope} onChange={(e) => setScope(e.target.value)}>
            <option value="all">All my productions</option>
            {projects.map((p) => (
              <option value={p.id} key={p.id}>
                {p.title}
              </option>
            ))}
          </select>
        </label>
        <label className="check-label">
          <input
            type="checkbox"
            checked={showDone}
            onChange={(e) => setShowDone(e.target.checked)}
          />
          Include finished and stopped work
        </label>
      </div>
      {!shown.length && (
        <p className="panel">
          {scoped.length
            ? "Nothing is waiting or running here. Turn on finished work to view the history."
            : "No work has been requested yet."}
        </p>
      )}
      {shown.map((j) => (
        <article className="panel activity-card" key={j.id}>
          <div>
            <strong>
              {kinds[j.kind] || "Studio task"} · {status[j.status] || j.status}
            </strong>
            <h3>
              {j.snapshot.scene_title ||
                j.snapshot.title ||
                projects.find((p) => p.id === j.project_id)?.title ||
                (j.snapshot.setup_probe ? "Creation tool sample" : "Saved video")}
            </h3>
            <p>
              {j.snapshot.setup_probe ? "Setup check: " : j.kind==='outline' ? "Production: " : "Video: "}
              {projects.find((p) => p.id === j.project_id)?.title ||
                (j.snapshot.setup_probe ? "Voices, music or effects" : j.kind==='outline' ? j.snapshot.title : "Archived video")}
            </p>
          </div>
          {!["completed", "superseded", "cancelled"].includes(j.status) && (
            <p>
              {j.status === "failed"
                ? "This task could not finish. Your earlier versions remain available."
                : j.status === "needs_attention"
                  ? "The original result is uncertain. Review it before starting another copy."
                  : j.status === "awaiting_review"
                    ? "Open the video and review the scene or planning proposal."
                    : j.status === "queued"
                      ? "Waiting for its turn, your review, or available resources."
                      : ["speech","music","effects"].includes(j.kind) && !j.progress ? "Loading and creating sound. This can take several minutes; other graphics tasks wait their turn." : `${Math.round(j.progress * 100)}% of the current stage`}
            </p>
          )}
          <div className="button-row">
            <button className="button" onClick={() => j.snapshot.setup_probe && goSetup ? goSetup() : j.kind==='outline' && openProduction ? openProduction(j.snapshot.production_id) : choose(j.project_id)}>
              {j.snapshot.setup_probe ? "Open tool setup" : j.kind==='outline' ? "Open production plan" : "Open video"}
            </button>
            {["failed", "cancelled"].includes(j.status) && (
              <button
                className="button"
                onClick={() =>
                  act(
                    () => j.snapshot.setup_probe ? request(`/api/setup/packs/${j.snapshot.pack_id}/sample`,{seconds:j.snapshot.inputs?.seconds,vocal:j.snapshot.inputs?.instrumental===false}) : request(`/api/jobs/${j.id}/retry`, {}),
                    "A new attempt was requested.",
                  )
                }
              >
                Try again as a new version
              </button>
            )}
            {j.status === "queued" && (
              <button
                className="button"
                onClick={() =>
                  act(
                    () => request(`/api/jobs/${j.id}/cancel`, {}),
                    "This waiting task was stopped.",
                  )
                }
              >
                Stop this waiting task
              </button>
            )}
            {["submitted", "reconciling"].includes(j.status) &&
              ["image", "video", "speech", "music", "effects"].includes(j.kind) && (
                <button
                  className="button"
                  onClick={() =>
                    act(
                      () => request(`/api/jobs/${j.id}/cancel`, {}),
                      "Requested a stop for this task only.",
                    )
                  }
                >
                  Stop this task
                </button>
              )}
          </div>
          {j.status === "needs_attention" && (
            <details>
              <summary>Review the original result before retrying</summary>
              <p>
                Check the original task and its output in your local tools. A
                new attempt can create another version.
              </p>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={!!reviewed[j.id]}
                  onChange={(e) =>
                    setReviewed({ ...reviewed, [j.id]: e.target.checked })
                  }
                />
                I checked the original result
              </label>
              <button
                className="button"
                disabled={!reviewed[j.id]}
                onClick={() =>
                  act(
                    () =>
                      request(`/api/jobs/${j.id}/retry`, {
                        confirm_uncertain: true,
                      }),
                    "A reviewed new attempt was requested.",
                  )
                }
              >
                Create a new reviewed attempt
              </button>
            </details>
          )}
          <details>
            <summary>Task details</summary>
            {j.error && <p className="error-text">{j.error}</p>}
            <p>
              Task {j.id} · backend request{" "}
              {j.comfy_prompt_id || "not confirmed"}
            </p>
            <pre>{JSON.stringify(j.snapshot, null, 2)}</pre>
            {j.status === "queued" && (
              <button
                className="button"
                onClick={() =>
                  act(
                    () =>
                      request(`/api/jobs/${j.id}/priority`, { priority: 80 }),
                    "Moved ahead of other waiting tasks.",
                  )
                }
              >
                Move ahead of other waiting tasks
              </button>
            )}
          </details>
        </article>
      ))}
    </section>
  );
}
