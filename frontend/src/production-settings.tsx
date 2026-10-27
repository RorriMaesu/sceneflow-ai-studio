import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request } from "./api";
import type { Project, Workflow } from "./types";
import { useRecoverableDraft, DraftNotice } from "./recoverable-draft";

export function ProductionSettings({
  project,
  workflows,
  models,
  act,
}: {
  project: Project;
  workflows: Workflow[];
  models: any[];
  act: any;
}) {
  const draft = useRecoverableDraft(
    "settings." + project.id,
    { settings: project.settings, brief: project.brief },
    project.revision,
    (v) => !!v?.settings && typeof v?.brief === "string",
  );
  const values = draft.value.settings,
    brief = draft.value.brief,
    dirty = draft.dirty,
    base = draft.revision;
  const setValues = (next: import("react").SetStateAction<typeof values>) =>
    draft.setValue((v) => ({
      ...v,
      settings: typeof next === "function" ? next(v.settings) : next,
    }));
  const setBrief = (brief: string) => draft.setValue((v) => ({ ...v, brief }));
  const available = useQuery<any[]>({
    queryKey: ["vision-models"],
    queryFn: () => request("/api/language-models"),
    staleTime: 60000,
  });
  const set = (key: string, value: any) => {
    setValues((v) => ({ ...v, [key]: value }));
  };
  return (
    <details className="panel production-settings">
      <summary>
        Production settings · models, approvals & creative brief
      </summary>
      <DraftNotice draft={draft} />
      <div className="settings-grid">
        <label>
          Creative brief
          <textarea
            rows={3}
            value={brief}
            onChange={(e) => {
              setBrief(e.target.value);
            }}
          />
        </label>
        <p>Edit style and character references in Look & photos.</p>
        <label>
          Planning model
          <select
            value={values.llm || ""}
            onChange={(e) => set("llm", e.target.value)}
          >
            <option value="">Select installed model</option>
            {models.map((m) => (
              <option key={m.name}>{m.name}</option>
            ))}
          </select>
        </label>
        {(["image", "video"] as const).map((kind) => (
          <label key={kind}>
            {kind === "image" ? "Still-image" : "Video"} workflow
            <select
              value={values[kind + "_workflow"]}
              onChange={(e) => set(kind + "_workflow", e.target.value)}
            >
              {workflows
                .filter((w) =>
                  kind === "image"
                    ? w.task === "text_to_image"
                    : w.task === "image_to_video",
                )
                .map((w) => (
                  <option
                    key={w.id}
                    value={w.id}
                    disabled={w.status !== "ready"}
                  >
                    {w.name}
                    {w.status !== "ready" ? " · unavailable" : ""}
                  </option>
                ))}
            </select>
          </label>
        ))}
        <label>
          Still candidates
          <input
            type="number"
            min={1}
            max={4}
            value={values.candidates}
            onChange={(e) => set("candidates", Number(e.target.value))}
          />
        </label>
        <label>
          Image steps
          <input
            type="number"
            min={1}
            max={60}
            value={values.image_steps}
            onChange={(e) => set("image_steps", Number(e.target.value))}
          />
        </label>
        <label>
          Generation preset
          <select
            value=""
            onChange={(e) => {
              const presets: any = {
                draft: { width: 640, height: 352, image_steps: 8 },
                reference: { width: 640, height: 352, image_steps: 20 },
                detail: { width: 640, height: 352, image_steps: 25 },
                larger: { width: 832, height: 480, image_steps: 25 },
              };
              if (presets[e.target.value]) {
                setValues((v) => ({ ...v, ...presets[e.target.value] }));
              }
            }}
          >
            <option value="">Choose a preset or keep custom settings</option>
            <option value="draft">Fast draft · 640×352 · 8 steps</option>
            <option value="reference">
              Reference proof · 640×352 · 20 steps
            </option>
            <option value="detail">
              More image steps · 640×352 · 25 steps
            </option>
            <option value="larger">
              Higher resolution experiment · 832×480 · 25 steps
            </option>
          </select>
        </label>
        <label>
          Attempts per new video stage
          <input
            type="number"
            min={1}
            max={4}
            value={values.video_attempts || 1}
            onChange={(e) => set("video_attempts", Number(e.target.value))}
          />
        </label>
        <label>
          Native width
          <input
            type="number"
            min={64}
            max={2048}
            step={32}
            value={values.width}
            onChange={(e) => set("width", Number(e.target.value))}
          />
        </label>
        <label>
          Native height
          <input
            type="number"
            min={64}
            max={2048}
            step={32}
            value={values.height}
            onChange={(e) => set("height", Number(e.target.value))}
          />
        </label>
        <label>
          Maximum quality retries
          <input
            type="number"
            min={0}
            max={2}
            value={values.max_retries ?? 2}
            onChange={(e) => set("max_retries", Number(e.target.value))}
          />
        </label>
        <label>
          Elapsed production budget (minutes, 0 = unlimited)
          <input
            type="number"
            min={0}
            max={1440}
            value={values.run_budget_minutes || 0}
            onChange={(e) => set("run_budget_minutes", Number(e.target.value))}
          />
        </label>
        <label>
          When an automatic job fails
          <select
            value={values.failure_policy || "continue"}
            onChange={(e) => set("failure_policy", e.target.value)}
          >
            <option value="continue">Continue independent scenes</option>
            <option value="stop">Pause this production for review</option>
            <option value="partial">
              Continue, then export a labeled partial preview
            </option>
          </select>
        </label>
        <label>
          Vision QA model
          <select
            value={values.qa_model || ""}
            onChange={(e) => set("qa_model", e.target.value)}
          >
            <option value="">Select independently from planning model</option>
            <option value="auto">Auto-select an installed vision model</option>
            {available.data
              ?.filter((m) => m.capabilities.includes("vision"))
              .map((m) => (
                <option key={m.name}>{m.name}</option>
              ))}
          </select>
        </label>
      </div>
      <div className="quality-settings">
        <label>
          <input
            type="checkbox"
            checked={!!values.qa_enabled}
            onChange={(e) => set("qa_enabled", e.target.checked)}
          />{" "}
          AI Quality Control — {values.qa_enabled ? "On" : "Off"}
        </label>
        <p className="muted">
          Optional local visual review uses extra memory and time. Manual
          approval always wins.{" "}
          {available.isError
            ? "Ollama discovery is unavailable; manual review remains available."
            : ""}
        </p>
        <div className="settings-grid">
          <label>
            Rubric
            <select
              value={values.qa_rubric || "balanced"}
              onChange={(e) => set("qa_rubric", e.target.value)}
            >
              {["lenient", "balanced", "strict"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            Still review
            <select
              value={values.qa_image_mode || "every"}
              onChange={(e) => set("qa_image_mode", e.target.value)}
            >
              {["every", "selected", "suspicious", "off"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            Video review
            <select
              value={values.qa_video_mode || "every"}
              onChange={(e) => set("qa_video_mode", e.target.value)}
            >
              {["every", "suspicious", "off"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={values.qa_auto !== false}
              onChange={(e) => set("qa_auto", e.target.checked)}
            />{" "}
            Run checks automatically when enabled
          </label>
          <label>
            <input
              type="checkbox"
              checked={!!values.qa_regenerate}
              onChange={(e) => set("qa_regenerate", e.target.checked)}
            />{" "}
            Retry actionable visual failures (maximum two per stage)
          </label>
        </div>
      </div>
      <p className="muted">
        Hybrid pauses at the checked reviews. Automatic uses technically valid
        takes; Manual launches only work you request. An active render keeps its
        saved inputs.
      </p>
      <p className="muted">
        The budget includes loading, waiting and review time. It is checked
        before a new automatic job; an active render finishes. Resume starts a
        fresh budget window. Draft settings trade detail for speed; larger
        presets require local measurement.
      </p>
      <div className="button-row">
        {["storyboard", "prompts", "image", "video", "timeline"].map((g) => (
          <label key={g}>
            <input
              type="checkbox"
              checked={!!values.gates?.[g]}
              onChange={(e) =>
                set("gates", { ...values.gates, [g]: e.target.checked })
              }
            />{" "}
            Review {g}
          </label>
        ))}
      </div>
      <div className="button-row">
        <label>
          <input
            type="checkbox"
            checked={!!values.auto_export}
            onChange={(e) => set("auto_export", e.target.checked)}
          />{" "}
          Export automatically when reviews are clear
        </label>
      </div>
      {dirty && project.revision > base && (
        <p role="alert">
          The project changed elsewhere. Reload these controls before replacing
          newer settings.
        </p>
      )}
      <div className="button-row">
        <button
          className="button primary"
          disabled={!dirty || draft.conflict}
          onClick={() =>
            act(async () => {
              const p = await request(
                `/api/projects/${project.id}`,
                { revision: base, brief, settings: values },
                "PATCH",
              );
              draft.adopt({ settings: p.settings, brief: p.brief }, p.revision);
            }, "Production settings saved.")
          }
        >
          Save production settings
        </button>
        <button
          className="button"
          onClick={() =>
            act(
              () => request(`/api/projects/${project.id}/approve-planning`, {}),
              "Current storyboard and prompts approved.",
            )
          }
        >
          Approve current storyboard & prompts
        </button>
      </div>
    </details>
  );
}
