import React, { useEffect, useRef, useState } from "react";
import type { Bootstrap, Job } from "./types";

export function ReadinessCoach({
  data,
  onSettings,
  onModels,
}: {
  data?: Bootstrap;
  onSettings: () => void;
  onModels: () => void;
}) {
  const connected = !!data;
  const comfy = !!data?.services.comfy.connected;
  const count = data?.projects.length || 0;
  return (
    <details className="panel readiness-coach" open={!connected || !comfy}>
      <summary>
        {connected && comfy
          ? "Studio ready · startup guidance"
          : "Finish connecting your studio"}
      </summary>
      <p>
        {!connected
          ? "Start the local agent and pair this browser."
          : !comfy
            ? "Start ComfyUI, then refresh the workflow library."
            : !count
              ? "Your local services are connected. Create a project, choose a visual reference and add your first scene."
              : "Open a production to review its visual bible, selected takes and waiting jobs."}
      </p>
      <div className="readiness-steps">
        <span className={connected ? "ready" : ""}>
          1 · Agent {connected ? "connected" : "needed"}
        </span>
        <span className={comfy ? "ready" : ""}>
          2 · ComfyUI {comfy ? "connected" : "needed"}
        </span>
        <span className={count ? "ready" : ""}>
          3 · {count} saved production{count === 1 ? "" : "s"}
        </span>
      </div>
      <div className="button-row">
        <button className="button" onClick={onSettings}>
          Connection & readiness
        </button>
        <button className="button" onClick={onModels}>
          Check installed workflows
        </button>
      </div>
    </details>
  );
}

export function NotificationSettings() {
  const supported = typeof Notification !== "undefined";
  const [permission, setPermission] = useState(
    supported ? Notification.permission : "unsupported",
  );
  const [enabled, setEnabled] = useState(
    localStorage.getItem("sceneflow.notifications") === "on",
  );
  return (
    <details className="panel">
      <summary>Completion notifications</summary>
      <p>
        Notify this browser when a generation or export completes or fails. The
        browser must remain open; the local agent keeps producing if you close
        it.
      </p>
      <p>
        Permission: {permission} · {enabled ? "Enabled" : "Off"}
      </p>
      <button
        className="button"
        disabled={!supported}
        onClick={async () => {
          if (enabled) {
            localStorage.setItem("sceneflow.notifications", "off");
            setEnabled(false);
            return;
          }
          const result = await Notification.requestPermission();
          setPermission(result);
          if (result === "granted") {
            localStorage.setItem("sceneflow.notifications", "on");
            setEnabled(true);
          }
        }}
      >
        {enabled ? "Turn notifications off" : "Enable browser notifications"}
      </button>
    </details>
  );
}

export function useCompletionNotifications(
  jobs: Job[],
  notify: (s: string) => void,
) {
  const known = useRef<Map<string, string>>(new Map());
  const ready = useRef(false);
  useEffect(() => {
    if (!jobs.length) return;
    if (!ready.current) {
      known.current = new Map(jobs.map((j) => [j.id, j.status]));
      ready.current = true;
      return;
    }
    for (const job of jobs) {
      const old = known.current.get(job.id);
      if (
        old &&
        old !== job.status &&
        ["completed", "failed", "needs_attention"].includes(job.status)
      ) {
        const message = `${job.kind === "export" ? "Movie export" : job.kind === "image" ? "Still generation" : job.kind === "video" ? "Animation" : "Studio job"} ${job.status === "completed" ? "completed" : job.status === "failed" ? "needs review after a failure" : "needs your attention"}.`;
        notify(message);
        if (
          typeof Notification !== "undefined" &&
          Notification.permission === "granted" &&
          localStorage.getItem("sceneflow.notifications") === "on" &&
          document.hidden
        )
          new Notification("SceneFlow", { body: message, tag: job.id });
      }
      known.current.set(job.id, job.status);
    }
  }, [jobs.map((j) => j.id + ":" + j.status).join("|")]);
}

export class StudioBoundary extends React.Component<
  React.PropsWithChildren,
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    if (this.state.failed)
      return (
        <main className="fatal-recovery">
          <h1>Your saved studio is still on your PC.</h1>
          <p>
            The interface encountered a problem. Reload to reconnect to the
            agent. Saved projects, takes and active generation remain with the
            local agent.
          </p>
          <button className="button primary" onClick={() => location.reload()}>
            Reload studio
          </button>
        </main>
      );
    return this.props.children;
  }
}
