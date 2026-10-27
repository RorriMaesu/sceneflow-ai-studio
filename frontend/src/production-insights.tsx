import { useQuery } from "@tanstack/react-query";
import { request } from "./api";
import type { Project } from "./types";

export function ProductionInsights({ project }: { project: Project }) {
  const result = useQuery<any>({
    queryKey: ["performance", project.id],
    queryFn: () => request(`/api/projects/${project.id}/performance`),
    refetchInterval: 12000,
  });
  const data = result.data;
  return (
    <details className="panel">
      <summary>Timing details · measured on this computer</summary>
      <p>
        <strong>
          AI quality control: {project.settings.qa_enabled ? "On" : "Off"}
        </strong>{" "}
        · {data ? (data.production.paused ? "New automatic work paused" : "Production can continue") : "Checking status…"}
      </p>
      {data?.run?.reason && <p role="status">{data.run.reason}</p>}
      <p>
        Native generation: {project.settings.width} × {project.settings.height}.
        Export size is configured separately in the timeline.
      </p>
      {data?.queued_observed_range_seconds && (
        <p>
          Measured presets suggest about{" "}
          {(data.queued_observed_range_seconds[0] / 60).toFixed(1)}–
          {(data.queued_observed_range_seconds[1] / 60).toFixed(1)} minutes for
          matching queued generation jobs.{" "}
          {data.unknown_jobs > 0
            ? `${data.unknown_jobs} other jobs have no matching timing sample.`
            : ""}
        </p>
      )}
      <p className="muted">
        {data?.note ||
          "Timings appear after real completed generation. No estimate is invented for an unmeasured preset."}
      </p>
      <div className="timing-table">
        {data?.presets.map((p: any, i: number) => (
          <p key={i}>
            {p.kind} · {p.workflow} · {p.width}×{p.height} ·{" "}
            {p.steps ? `${p.steps} steps` : `${p.frames} frames`} · median{" "}
            {p.median_seconds}s · observed {p.min_seconds}–{p.max_seconds}s
            across {p.samples} run{p.samples === 1 ? "" : "s"}
          </p>
        ))}
      </div>
    </details>
  );
}
