import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request, upload, useConnection } from "./api";
import type { Asset, Project, Scene } from "./types";
import { AssetQuality } from "./quality-panel";
import { useRecoverableDraft, DraftNotice } from "./recoverable-draft";

export function SceneKeyframes({
  scene,
  project,
  body,
  change,
  renderMedia,
}: {
  scene: Scene;
  project: Project;
  body: any;
  change: (key: string, value: any) => void;
  renderMedia: (a: Asset) => React.ReactNode;
}) {
  const assets = useQuery<Asset[]>({
    queryKey: ["project-assets", project.id],
    queryFn: () => request("/api/assets?project_id=" + project.id),
    refetchInterval: 15000,
  });
  const images =
    assets.data?.filter(
      (a) => a.kind === "image" && a.metadata.role !== "edit_mask",
    ) || [];
  const ending = images.find((a) => a.id === body.ending_asset_id);
  const starting = scene.assets.find((a) => a.id === scene.selected_image_id);
  return (
    <details className="scene-keyframes">
      <summary>Starting & ending frames</summary>
      <p>
        Choose an optional ending image from this project. The native Wan
        first/last adapter guides both ends while keeping the selected starting
        still. It reuses the installed models.
      </p>
      <label>
        Ending frame
        <select
          value={body.ending_asset_id || ""}
          onChange={(e) => change("ending_asset_id", e.target.value || null)}
        >
          <option value="">No ending frame · ordinary animation</option>
          {images.map((a) => (
            <option key={a.id} value={a.id}>
              {project.scenes.find((s) => s.id === a.scene_id)?.title ||
                a.metadata.original_name ||
                "Project reference"}{" "}
              · {a.id.slice(0, 8)}
            </option>
          ))}
        </select>
      </label>
      <button
        className="button"
        disabled={!scene.selected_image_id}
        onClick={() => change("ending_asset_id", scene.selected_image_id)}
      >
        Use the starting still as the loop ending
      </button>
      <div className="comparison-pair">
        <div>
          <p>Starting still</p>
          {starting && renderMedia(starting)}
        </div>
        <div>
          <p>Ending target</p>
          {ending ? renderMedia(ending) : <p className="muted">Optional</p>}
        </div>
      </div>
      <p className="muted">
        Save scene settings before animating. Ending-frame changes invalidate
        animation inputs while preserving the still and earlier takes. Matching
        conditioning images cannot guarantee exact ending pixels or a seamless
        loop.
      </p>
    </details>
  );
}

export function VisualBible({
  project,
  act,
  renderMedia,
}: {
  project: Project;
  act: any;
  renderMedia: (a: Asset) => React.ReactNode;
}) {
  const assets = useQuery<Asset[]>({
    queryKey: ["project-assets", project.id],
    queryFn: () => request("/api/assets?project_id=" + project.id),
    refetchInterval: 15000,
  });
  const draft = useRecoverableDraft(
    "look." + project.id,
    {
      chosen: project.settings.reference_asset_ids || [],
      rules: project.settings.visual_rules || "",
      style: project.settings.style_guide || "",
    },
    project.revision,
    (v) => Array.isArray(v?.chosen) && typeof v?.rules === "string",
  );
  const { chosen, rules } = draft.value;
  const style =
    (draft.value as any).style ?? project.settings.style_guide ?? "";
  const dirty = draft.dirty,
    base = draft.revision;
  const setChosen = (chosen: string[]) =>
    draft.setValue((v) => ({ ...v, chosen }));
  const setRules = (rules: string) => draft.setValue((v) => ({ ...v, rules }));
  const images =
    assets.data?.filter(
      (a) => a.kind === "image" && a.metadata.role !== "edit_mask",
    ) || [];
  return (
    <details className="panel visual-bible">
      <summary>
        Look & characters · reference pictures{" "}
        {chosen.length ? `· ${chosen.length} selected` : ""}
      </summary>
      <DraftNotice draft={draft} />
      <p>
        Choose up to three approved images to guide every new still. Image 1
        sets the initial framing. The original files and their hashes stay
        attached to each attempt. References guide appearance; they do not
        guarantee identity.
      </p>
      <label>
        Overall visual style
        <textarea
          rows={2}
          maxLength={5000}
          value={style}
          onChange={(e) =>
            draft.setValue((v) => ({ ...v, style: e.target.value }))
          }
          placeholder="For example: warm storybook illustration, soft light and rich colors."
        />
      </label>
      <label>
        Details to keep consistent
        <textarea
          rows={3}
          value={rules}
          onChange={(e) => {
            setRules(e.target.value);
          }}
          placeholder="Character silhouette, face, costume, colors, lighting and details that must stay the same."
        />
      </label>
      <label className="upload-label">
        Import a visual reference
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file)
              act(async () => {
                await upload(
                  `/api/projects/${project.id}/references/import`,
                  file,
                );
                assets.refetch();
              }, "Reference imported. Select it below, then save the visual bible.");
          }}
        />
      </label>
      <div className="reference-grid">
        {images.map((a) => (
          <label
            className={
              "reference-card " + (chosen.includes(a.id) ? "selected" : "")
            }
            key={a.id}
          >
            {renderMedia(a)}
            <span>
              <input
                type="checkbox"
                checked={chosen.includes(a.id)}
                disabled={!chosen.includes(a.id) && chosen.length >= 3}
                onChange={(e) => {
                  setChosen(
                    e.target.checked
                      ? [...chosen, a.id]
                      : chosen.filter((id: string) => id !== a.id),
                  );
                }}
              />{" "}
              {chosen.includes(a.id)
                ? `Reference ${chosen.indexOf(a.id) + 1}`
                : a.metadata.original_name || "Scene still"}
            </span>
          </label>
        ))}
      </div>
      {dirty && project.revision > base && (
        <p role="alert">
          This project changed elsewhere. Reload the visual bible before
          replacing newer settings.
        </p>
      )}
      <p className="muted">
        Changing saved rules or references makes affected image and animation
        selections outdated. Active jobs retain their original inputs and
        previous takes remain available.
      </p>
      <button
        className="button primary"
        disabled={!dirty || draft.conflict}
        onClick={() =>
          act(async () => {
            const p = await request(
              `/api/projects/${project.id}`,
              {
                revision: base,
                settings: {
                  reference_asset_ids: chosen,
                  visual_rules: rules,
                  style_guide: style,
                },
              },
              "PATCH",
            );
            draft.adopt(
              {
                chosen: p.settings.reference_asset_ids || [],
                rules: p.settings.visual_rules || "",
                style: p.settings.style_guide || "",
              },
              p.revision,
            );
          }, "Visual bible saved. Future jobs use the new references and rules.")
        }
      >
        Save look & references
      </button>
    </details>
  );
}

export function CorrectionCanvas({
  asset,
  project,
  act,
  renderMedia,
}: {
  asset: Asset;
  project: Project;
  act: any;
  renderMedia: (a: Asset) => React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setExpanded(false);
    };
    if (expanded) window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [expanded]);
  const canvas = useRef<HTMLCanvasElement>(null);
  const drawing = useRef(false);
  const last = useRef<[number, number] | null>(null);
  const history = useRef<ImageData[]>([]);
  const [revision, setRevision] = useState(0);
  const [painted, setPainted] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [brush, setBrush] = useState(40);
  const [zoom, setZoom] = useState(1);
  const [erase, setErase] = useState(false);
  const [masked, setMasked] = useState(true);
  const [steps, setSteps] = useState(25);
  const [strength, setStrength] = useState(0.6);
  const ticket = useQuery<{ url: string }>({
    queryKey: ["edit-source", asset.id],
    queryFn: () => request(`/api/assets/${asset.id}/ticket`, {}),
    staleTime: 20 * 60 * 1000,
    enabled: open,
  });
  const width = asset.metadata.width,
    height = asset.metadata.height;
  const reset = () => {
    const ctx = canvas.current?.getContext("2d");
    if (ctx) {
      ctx.fillStyle = "black";
      ctx.fillRect(0, 0, width, height);
      history.current = [];
      setRevision((v) => v + 1);
      setPainted(false);
    }
  };
  useEffect(reset, [asset.id, open]);
  const point = (
    e: React.PointerEvent<HTMLCanvasElement>,
  ): [number, number] => {
    const r = e.currentTarget.getBoundingClientRect();
    return [
      ((e.clientX - r.left) * width) / r.width,
      ((e.clientY - r.top) * height) / r.height,
    ];
  };
  const stroke = (e: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawing.current) return;
    const ctx = canvas.current!.getContext("2d")!;
    const p = point(e);
    ctx.strokeStyle = erase ? "black" : "white";
    ctx.shadowColor = erase ? "black" : "white";
    ctx.shadowBlur = 5;
    ctx.lineWidth = brush;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(...(last.current || p));
    ctx.lineTo(p[0] + 0.01, p[1] + 0.01);
    ctx.stroke();
    last.current = p;
    setPainted(true);
  };
  return (
    <details
      className={"correction-panel" + (expanded ? " correction-expanded" : "")}
      onToggle={(e) => setOpen(e.currentTarget.open)}
    >
      <summary>Correct this still · preserve the original</summary>
      {open && (
        <>
          <button className="button" onClick={() => setExpanded((v) => !v)}>
            {expanded ? "Return to scene" : "Expand editor"}
          </button>
          <p>
            Describe a change. Paint white over the area to replace. Black areas
            are copied from the original after generation and checked pixel by
            pixel. Source-based masked sampling and visual references guide the
            correction.
          </p>
          <label>
            Correction instructions
            <textarea
              value={prompt}
              rows={3}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="In <image1>, change only the lantern flame to blue. Keep the composition and other details."
            />
          </label>
          <div className="button-row">
            <label>
              <input
                type="checkbox"
                checked={masked}
                onChange={(e) => setMasked(e.target.checked)}
              />{" "}
              Limit to painted area
            </label>
            <label>
              Brush size
              <input
                type="range"
                min={4}
                max={180}
                value={brush}
                onChange={(e) => setBrush(Number(e.target.value))}
              />
            </label>
            <button className="button" onClick={() => setErase((v) => !v)}>
              {erase ? "Eraser on" : "Paint brush"}
            </button>
            <button
              className="button"
              disabled={!revision || !history.current.length}
              onClick={() => {
                const image = history.current.pop();
                if (image)
                  canvas.current!.getContext("2d")!.putImageData(image, 0, 0);
                setRevision((v) => v + 1);
                setPainted(!!history.current.length);
              }}
            >
              Undo brush
            </button>
            <button className="button" onClick={reset}>
              Clear mask
            </button>
          </div>
          <label>
            Canvas zoom
            <input
              type="range"
              min={0.5}
              max={2.5}
              step={0.1}
              value={zoom}
              onChange={(e) => setZoom(Number(e.target.value))}
            />
          </label>
          <div className="correction-scroll">
            <div
              className="correction-surface"
              style={{
                width: Math.max(280, Math.min(width, 700)) * zoom,
                aspectRatio: `${width}/${height}`,
              }}
            >
              {ticket.data && (
                <img
                  alt="Original correction target"
                  src={useConnection.getState().url + ticket.data.url}
                />
              )}
              <canvas
                ref={canvas}
                width={width}
                height={height}
                aria-label="Paint correction mask"
                style={{ display: masked ? "block" : "none" }}
                onPointerDown={(e) => {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  const ctx = e.currentTarget.getContext("2d")!;
                  history.current = [
                    ...history.current.slice(-19),
                    ctx.getImageData(0, 0, width, height),
                  ];
                  drawing.current = true;
                  last.current = null;
                  stroke(e);
                }}
                onPointerMove={stroke}
                onPointerUp={() => {
                  drawing.current = false;
                  last.current = null;
                  setRevision((v) => v + 1);
                }}
                onPointerCancel={() => {
                  drawing.current = false;
                  last.current = null;
                }}
              />
            </div>
          </div>
          <label>
            Change strength
            <input
              type="range"
              min={0.1}
              max={1}
              step={0.05}
              value={strength}
              onChange={(e) => setStrength(Number(e.target.value))}
            />
            {strength.toFixed(2)}
          </label>
          <label>
            Correction steps
            <input
              type="number"
              min={1}
              max={60}
              value={steps}
              onChange={(e) => setSteps(Number(e.target.value))}
            />
          </label>
          <p className="muted">
            25 steps follows the installed editing template. More steps take
            longer. New results appear as separate takes for your approval.
          </p>
          <button
            className="button primary"
            disabled={prompt.trim().length < 5 || (masked && !painted)}
            onClick={() =>
              act(async () => {
                let maskId: string | undefined;
                if (masked) {
                  const blob = await new Promise<Blob>((resolve, reject) =>
                    canvas.current!.toBlob(
                      (b) =>
                        b
                          ? resolve(b)
                          : reject(new Error("Could not save mask.")),
                      "image/png",
                    ),
                  );
                  const result = await upload(
                    `/api/assets/${asset.id}/mask`,
                    new File([blob], "mask.png", { type: "image/png" }),
                  );
                  maskId = result.asset_id;
                }
                return request(`/api/assets/${asset.id}/correct`, {
                  prompt,
                  mask_asset_id: maskId,
                  steps,
                  strength,
                });
              }, "Correction queued as a new take. The original remains unchanged.")
            }
          >
            Generate correction
          </button>
          {project.scenes
            .flatMap((s) => s.assets)
            .filter(
              (a) =>
                a.source_asset_id === asset.id && a.metadata.edit_operation,
            )
            .map((a) => (
              <div className="correction-result" key={a.id}>
                <h4>
                  Correction result{" "}
                  {a.metadata.outside_mask_unchanged
                    ? "· outside mask verified"
                    : ""}
                </h4>
                <div className="comparison-pair">
                  <div>
                    <p>Before</p>
                    {renderMedia(asset)}
                  </div>
                  <div>
                    <p>After</p>
                    {renderMedia(a)}
                  </div>
                </div>
              </div>
            ))}
        </>
      )}
    </details>
  );
}

export function CandidateReview({
  scene,
  project,
  act,
  renderMedia,
}: {
  scene: Scene;
  project: Project;
  act: any;
  renderMedia: (a: Asset) => React.ReactNode;
}) {
  const [ids, setIds] = useState<string[]>([]);
  const images = scene.assets.filter((a) => a.kind === "image");
  const chosen = images.filter((a) => ids.includes(a.id));
  return (
    <details className="candidate-review">
      <summary>Compare photo options</summary>
      <p>
        Choose up to four takes. Compare the actual images and approve the one
        that preserves your visual rules.
      </p>
      <div className="button-row">
        {images.map((a, index) => (
          <label key={a.id}>
            <input
              type="checkbox"
              checked={ids.includes(a.id)}
              disabled={!ids.includes(a.id) && ids.length >= 4}
              onChange={(e) =>
                setIds(
                  e.target.checked
                    ? [...ids, a.id]
                    : ids.filter((id) => id !== a.id),
                )
              }
            />{" "}
            Take {images.length - index}
          </label>
        ))}
      </div>
      <div className="candidate-grid">
        {chosen.map((a) => (
          <article key={a.id}>
            {renderMedia(a)}
            <p>
              {a.metadata.width} × {a.metadata.height}
            </p>
            <AssetQuality asset={a} project={project} act={act} />
            <button
              className="button primary"
              onClick={() =>
                act(
                  () => request(`/api/assets/${a.id}/approve`, {}),
                  "Candidate selected and approved.",
                )
              }
            >
              Use this photo
            </button>
          </article>
        ))}
      </div>
      {chosen.length > 0 && (
        <button
          className="button"
          onClick={() =>
            act(async () => {
              for (const a of chosen)
                await request(`/api/assets/${a.id}/qa`, {
                  model: project.settings.qa_model || "auto",
                });
            }, "Selected candidates queued for independent reference-aware review.")
          }
        >
          Review compared candidates with AI
        </button>
      )}
    </details>
  );
}
