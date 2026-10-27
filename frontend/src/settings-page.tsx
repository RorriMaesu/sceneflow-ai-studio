import { useState } from "react";
import { request, useConnection } from "./api";
import { NotificationSettings } from "./studio-care";
import { MaintenancePanel } from "./maintenance-panel";
import type { Bootstrap } from "./types";
export function FriendlySettings({
  data,
  act,
  onPair,
  go,
}: {
  data?: Bootstrap;
  act: any;
  onPair: () => void;
  go: (p: string) => void;
  project?: any;
}) {
  const [comfy, setComfy] = useState(
      data?.settings.comfy_url || "http://127.0.0.1:8188",
    ),
    [ollama, setOllama] = useState(
      data?.settings.ollama_url || "http://127.0.0.1:11434",
    ),
    [code, setCode] = useState(""),
    [diagnostics, setDiagnostics] = useState<any>();
  return (
    <section className="friendly-settings">
      <h1>Settings</h1>
      <p>
        Your preferences and connection help. Creative settings belong inside
        each video.
      </p>
      {data && <section className="panel settings-panel"><h2>Creation tools and folders</h2><p>Add voices, music and other tools, choose where files go, and check for updates.</p><button className="button" onClick={() => go("Setup")}>Open setup & downloads</button></section>}
      <section className="panel settings-panel">
        <h2>Notifications</h2>
        <p>Choose how you would like to hear when work finishes.</p>
        <NotificationSettings />
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
          Windows tray alerts when the browser is closed
        </label>
        <p>
          Tray alerts require START_TRAY.bat to be running. Windows may suppress
          alerts according to its notification settings.
        </p>
      </section>
      <section className="panel settings-panel">
        <h2>Your local connection</h2>
        <p>
          {data
            ? "Connected to your studio on this computer."
            : "Start START_STUDIO.bat on your PC, then connect this browser."}
        </p>
        <div className="button-row">
          <button className="button" onClick={onPair}>
            {data ? "Pair a browser" : "Connect this browser"}
          </button>
          {data && (
            <button
              className="button"
              onClick={() =>
                act(
                  async () =>
                    setCode((await request("/api/session/pair-code", {})).code),
                  "A one-use code is ready below.",
                )
              }
            >
              Create a code for another browser
            </button>
          )}
          <button className="button" onClick={() => go("Help")}>
            Help me connect
          </button>
        </div>
        {code && (
          <p className="pair-code">
            One-use code: <strong>{code}</strong> · expires in 10 minutes. Keep
            it private.
          </p>
        )}
        <details>
          <summary>Advanced connection addresses</summary>
          <label>
            Photo and video service address
            <input value={comfy} onChange={(e) => setComfy(e.target.value)} />
          </label>
          <label>
            Story helper address
            <input value={ollama} onChange={(e) => setOllama(e.target.value)} />
          </label>
          <button
            className="button"
            disabled={!data}
            onClick={() =>
              act(
                () =>
                  request(
                    "/api/settings",
                    { comfy_url: comfy, ollama_url: ollama },
                    "PATCH",
                  ),
                "Connection addresses saved.",
              )
            }
          >
            Save connection addresses
          </button>
        </details>
      </section>
      <details className="panel settings-panel">
        <summary>Advanced tools, storage & troubleshooting</summary>
        <p>
          These controls are available when you need to diagnose a problem or
          manage installed tools.
        </p>
        <button className="button" onClick={() => go("Model Library")}>
          Check advanced creation tools
        </button>
        <MaintenancePanel data={data} act={act} maintenanceOnly />
        <div className="button-row">
          <button
            className="button"
            disabled={!data}
            onClick={() =>
              act(
                async () => setDiagnostics(await request("/api/diagnostics")),
                "Studio check complete.",
              )
            }
          >
            Check studio setup
          </button>
          <button
            className="button"
            disabled={!diagnostics}
            onClick={() => {
              const url = URL.createObjectURL(
                new Blob([JSON.stringify(diagnostics, null, 2)], {
                  type: "application/json",
                }),
              );
              const link = document.createElement("a");
              link.href = url;
              link.download = "SceneFlow-diagnostics.json";
              link.click();
              setTimeout(() => URL.revokeObjectURL(url), 1000);
            }}
          >
            Download support report
          </button>
        </div>
        {diagnostics && (
          <details>
            <summary>Support report details</summary>
            <pre>{JSON.stringify(diagnostics, null, 2)}</pre>
          </details>
        )}
        <details>
          <summary>Disconnect this browser</summary>
          <p>
            Your saved videos remain on this computer. You will need a fresh
            pairing code to reconnect.
          </p>
          <button
            className="button"
            onClick={() =>
              act(async () => {
                await request("/api/session/revoke", {});
                useConnection.getState().disconnect();
              }, "This browser was disconnected.")
            }
          >
            Disconnect this browser
          </button>
        </details>
      </details>
      <p className="muted">
        SceneFlow {data?.version || ""} · Projects, media and models stay local.
        Source updates are published separately.
      </p>
    </section>
  );
}
