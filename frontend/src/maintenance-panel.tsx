import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request, useConnection } from "./api";
import type { Bootstrap } from "./types";

export function MaintenancePanel({
  data,
  act,
}: {
  data?: Bootstrap;
  act: any;
}) {
  const paired = !!useConnection((s) => s.token);
  const [plan, setPlan] = useState<any>();
  const history = useQuery<any[]>({
    queryKey: ["maintenance"],
    queryFn: () => request("/api/maintenance/history"),
    enabled: paired,
  });
  return (
    <section className="panel settings-panel">
      <h3>Studio care</h3>
      <p>
        START_TRAY.bat adds an optional Windows tray menu to open the studio or
        stop its agent. Run it once per Windows session. Exiting the tray leaves
        the agent running.
      </p>
      <label className="check-label">
        <input
          type="checkbox"
          checked={!!data?.settings.desktop_notifications}
          disabled={!data}
          onChange={(e) =>
            act(
              () =>
                request(
                  "/api/settings",
                  { desktop_notifications: e.target.checked },
                  "PATCH",
                ),
              "Tray notification preference saved.",
            )
          }
        />
        Notify through the Windows tray while the browser is closed
      </label>
      <p className="muted">
        The tray must be running. Windows notification settings can suppress
        alerts. This is separate from browser notifications.
      </p>
      <h4>Review old export scratch files</h4>
      <p>
        Only export scratch folders from finished jobs older than a day are
        eligible. Quarantine moves them into a local recovery folder; it does
        not free drive space. Projects, models and installed tools are excluded.
      </p>
      <button
        className="button"
        disabled={!paired}
        onClick={() =>
          act(
            async () => setPlan(await request("/api/maintenance/review", {})),
            "Scratch review prepared.",
          )
        }
      >
        Review scratch files
      </button>
      {plan && (
        <div>
          <p>
            {plan.items.length} folders · {(plan.bytes / 1024 ** 2).toFixed(1)}{" "}
            MB · review expires after 15 minutes
          </p>
          {plan.items.map((item: any) => (
            <p className="muted" key={item.name}>
              {item.name} · {(item.bytes / 1024 ** 2).toFixed(1)} MB
            </p>
          ))}
          <button
            className="button"
            disabled={!plan.items.length}
            onClick={() =>
              act(async () => {
                await request(`/api/maintenance/${plan.id}/quarantine`, {});
                setPlan(undefined);
                await history.refetch();
              }, "Scratch files quarantined. Restore is available below.")
            }
          >
            Quarantine reviewed scratch files
          </button>
        </div>
      )}
      {history.data?.map((record) => (
        <div className="setting-row" key={record.id}>
          <span>
            {new Date(record.created * 1000).toLocaleString()} · {record.state}
          </span>
          {record.state !== "restored" && (
            <button
              className="button"
              onClick={() =>
                act(async () => {
                  await request(`/api/maintenance/${record.id}/restore`, {});
                  await history.refetch();
                }, "Scratch files restored without overwriting anything.")
              }
            >
              Restore scratch files
            </button>
          )}
        </div>
      ))}
    </section>
  );
}
