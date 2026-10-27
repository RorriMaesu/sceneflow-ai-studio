import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { request, upload } from "./api";
import { TimelinePreview, AudioWaveform } from "./timeline-preview";
import type { Asset, Project } from "./types";
import {useRecoverableDraft,DraftNotice} from "./recoverable-draft";

export function TimelineEditor({
  project,
  act,
  renderMedia,
}: {
  project: Project;
  act: any;
  renderMedia: (a?: Asset) => React.ReactNode;
}) {
  const draft=useRecoverableDraft('timeline.'+project.id,project.timeline,project.timeline.revision,v=>Array.isArray(v?.clips)&&Array.isArray(v?.audio)&&!!v?.settings);
  const {value,setValue,dirty}=draft;
  const revision=draft.revision;
  const [zoom,setZoom]=useState(1);
  const [past,setPast]=useState<any[]>([]);
  const [future,setFuture]=useState<any[]>([]);
  const dragged=useRef<number|null>(null);
  const assets = useQuery<Asset[]>({
    queryKey: ["project-assets", project.id],
    queryFn: () => request("/api/assets?project_id=" + project.id),
    refetchInterval: 10000,
  });
  const history = useQuery<any[]>({
    queryKey: ["timeline-history", project.id],
    queryFn: () => request(`/api/projects/${project.id}/timeline/history`),
    refetchInterval: 10000,
  });
  const change = (next: any) => {
    setPast((p) => [...p.slice(-49), value]);
    setFuture([]);
    setValue(next);
  };
  const clip = (index: number, changes: any) =>
    change({
      ...value,
      clips: value.clips.map((c: any, i: number) =>
        i === index ? { ...c, ...changes } : c,
      ),
    });
  const move = (from: number, to: number) => {
    if (from === to) return;
    const clips = [...value.clips];
    clips.splice(to, 0, clips.splice(from, 1)[0]);
    change({ ...value, clips });
  };
  const config = (key: string, v: any) =>
    change({ ...value, settings: { ...value.settings, [key]: v } });
  const audio = (index: number, changes: any) =>
    change({
      ...value,
      audio: value.audio.map((t: any, i: number) =>
        i === index ? { ...t, ...changes } : t,
      ),
    });
  const adopt = (v: any) => {
    draft.adopt(v,v.revision);
    setPast([]);
    setFuture([]);
    history.refetch();
  };
  const total = value.clips.reduce(
    (n: number, c: any) => n + (c.trim_out - (c.trim_in || 0)) / (c.speed || 1),
    0,
  );
  return (
    <section className="panel timeline-editor">
      <DraftNotice draft={draft}/>
      <div className="section-heading">
        <div>
          <h2>Your final cut</h2>
          <p>
            Drag clips into playback order. Native preview controls provide
            scrubbing and fullscreen. {total.toFixed(2)} s before transition
            overlaps.
          </p>
        </div>
        <div className="button-row">
          <button
            className="button"
            disabled={dirty}
            onClick={() =>
              act(
                async () =>
                  adopt(
                    await request(
                      `/api/projects/${project.id}/timeline/rebuild`,
                      {
                        partial: project.scenes.some(
                          (s) => !s.selected_video_id,
                        ),
                      },
                    ),
                  ),
                "Timeline built from selected takes.",
              )
            }
          >
            Build from chosen clips
          </button>
          <button
            className="button"
            disabled={!past.length}
            onClick={() => {
              setFuture((f) => [value, ...f]);
              setValue(past[past.length - 1]);
              setPast((p) => p.slice(0, -1));
                      }}
          >
            Undo
          </button>
          <button
            className="button"
            disabled={!future.length}
            onClick={() => {
              setPast((p) => [...p, value]);
              setValue(future[0]);
              setFuture((f) => f.slice(1));
                      }}
          >
            Redo
          </button>
          <button
            className="button primary"
            disabled={!dirty || draft.conflict || !value.clips.length}
            onClick={() =>
              act(
                async () =>
                  adopt(
                    await request(
                      `/api/projects/${project.id}/timeline`,
                      { ...value, revision },
                      "PATCH",
                    ),
                  ),
                "Timeline saved as a new version.",
              )
            }
          >
            Save edits
          </button>
        </div>
      </div>
      {dirty && project.timeline.revision !== revision && (
        <p role="alert">
          A newer timeline was saved elsewhere. Your draft is retained. Reload
          the saved version before replacing it.
        </p>
      )}
      <TimelinePreview value={value} />
      <label>
        Timeline zoom
        <input
          type="range"
          min={0.7}
          max={2}
          step={0.1}
          value={zoom}
          onChange={(e) => setZoom(Number(e.target.value))}
        />
      </label>
      <div className="edit-strip">
        {value.clips.map((c: any, index: number) => {
          const scene = project.scenes.find((s) => s.id === c.scene_id);
          const asset = scene?.assets.find((a) => a.id === c.asset_id);
          return (
            <article
              className="edit-clip"
              style={{ minWidth: 280 * zoom }}
              key={c.id}
              draggable
              onDragStart={() => {
                dragged.current = index;
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (dragged.current !== null) move(dragged.current, index);
                dragged.current = null;
              }}
            >
              <strong>
                {index + 1}. {scene?.title || "Clip"}
              </strong>
              {renderMedia(asset)}
              <div className="trim-handles">
                <label>
                  Start handle
                  <input
                    aria-label={`Clip ${index + 1} start handle`}
                    type="range"
                    min={0}
                    max={asset?.metadata.duration || c.trim_out}
                    step={1 / (asset?.metadata.fps || 30)}
                    value={c.trim_in || 0}
                    onChange={(e) =>
                      clip(index, {
                        trim_in: Math.min(
                          Number(e.target.value),
                          c.trim_out - 1 / (asset?.metadata.fps || 30),
                        ),
                      })
                    }
                  />
                </label>
                <label>
                  End handle
                  <input
                    aria-label={`Clip ${index + 1} end handle`}
                    type="range"
                    min={0}
                    max={asset?.metadata.duration || c.trim_out}
                    step={1 / (asset?.metadata.fps || 30)}
                    value={c.trim_out}
                    onChange={(e) =>
                      clip(index, {
                        trim_out: Math.max(
                          Number(e.target.value),
                          (c.trim_in || 0) + 1 / (asset?.metadata.fps || 30),
                        ),
                      })
                    }
                  />
                </label>
              </div>
              <div className="settings-grid">
                <label>
                  Trim in
                  <input
                    type="number"
                    min={0}
                    step={0.05}
                    value={c.trim_in || 0}
                    onChange={(e) =>
                      clip(index, { trim_in: Number(e.target.value) })
                    }
                  />
                </label>
                <label>
                  Trim out
                  <input
                    type="number"
                    min={0}
                    step={0.05}
                    value={c.trim_out}
                    onChange={(e) =>
                      clip(index, { trim_out: Number(e.target.value) })
                    }
                  />
                </label>
                <label>
                  Speed
                  <select
                    value={c.speed || 1}
                    onChange={(e) =>
                      clip(index, { speed: Number(e.target.value) })
                    }
                  >
                    {[0.25, 0.5, 0.75, 1, 1.25, 1.5, 2, 4].map((s) => (
                      <option key={s} value={s}>
                        {s}×
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Following transition
                  <select
                    value={c.transition || "inherit"}
                    onChange={(e) =>
                      clip(index, { transition: e.target.value })
                    }
                  >
                    {["inherit", "cut", "fade", "fade_black", "dissolve"].map(
                      (t) => (
                        <option key={t}>{t}</option>
                      ),
                    )}
                  </select>
                </label>
                <label>
                  Clip sound volume
                  <input
                    type="number"
                    step={0.1}
                    min={0}
                    max={4}
                    value={c.volume ?? 1}
                    onChange={(e) =>
                      clip(index, { volume: Number(e.target.value) })
                    }
                  />
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={!!c.mute}
                    onChange={(e) => clip(index, { mute: e.target.checked })}
                  />{" "}
                  Mute
                </label>
                <label>
                  Replace with take
                  <select
                    value={c.asset_id}
                    onChange={(e) => {
                      const a = scene?.assets.find(
                        (a) => a.id === e.target.value,
                      );
                      clip(index, {
                        asset_id: e.target.value,
                        trim_in: 0,
                        trim_out: a?.metadata.duration || 5,
                      });
                    }}
                  >
                    {scene?.assets
                      .filter((a) => a.kind === "video")
                      .map((a) => (
                        <option key={a.id} value={a.id}>
                          {a.id.slice(0, 8)}
                          {a.approved ? " · approved" : ""}
                        </option>
                      ))}
                  </select>
                </label>
              </div>
              <div className="button-row">
                <button
                  className="button"
                  disabled={index === 0}
                  onClick={() => move(index, index - 1)}
                  aria-label="Move clip earlier"
                >
                  ←
                </button>
                <button
                  className="button"
                  disabled={index === value.clips.length - 1}
                  onClick={() => move(index, index + 1)}
                  aria-label="Move clip later"
                >
                  →
                </button>
                <button
                  className="button"
                  onClick={() => {
                    const clips = [...value.clips];
                    clips.splice(index + 1, 0, {
                      ...c,
                      id: crypto.randomUUID(),
                    });
                    change({ ...value, clips });
                  }}
                >
                  Duplicate
                </button>
                <button
                  className="button"
                  onClick={() => {
                    const middle =
                      (Number(c.trim_in || 0) + Number(c.trim_out)) / 2;
                    const clips = [...value.clips];
                    clips.splice(
                      index,
                      1,
                      { ...c, trim_out: middle, transition: "cut" },
                      { ...c, id: crypto.randomUUID(), trim_in: middle },
                    );
                    change({ ...value, clips });
                  }}
                >
                  Split halfway
                </button>
                <button
                  className="button"
                  onClick={() =>
                    change({
                      ...value,
                      clips: value.clips.filter(
                        (_: any, i: number) => i !== index,
                      ),
                    })
                  }
                >
                  Remove
                </button>
              </div>
            </article>
          );
        })}
      </div>
      {!value.clips.length && (
        <p className="muted">
          Approve scene videos, then build a timeline. You can also import video
          takes in the scene inspector.
        </p>
      )}
      <details open>
        <summary>Sound tracks · music, voiceover & effects</summary>
        <label className="upload-label">
          Import audio
          <input
            type="file"
            accept=".wav,.mp3,.flac,.ogg,.m4a"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file)
                act(async () => {
                  await upload(
                    `/api/projects/${project.id}/import-media`,
                    file,
                  );
                  assets.refetch();
                }, "Audio imported. Add it to a track below.");
            }}
          />
        </label>
        <div className="button-row">
          {assets.data
            ?.filter((a) => a.kind === "audio")
            .map((a) => (
              <button
                className="button"
                key={a.id}
                onClick={() =>
                  change({
                    ...value,
                    audio: [
                      ...value.audio,
                      {
                        id: crypto.randomUUID(),
                        asset_id: a.id,
                        role: "music",
                        start: 0,
                        trim_in: 0,
                        trim_out: a.metadata.duration,
                        volume: 0.7,
                        fade_in: 0.2,
                        fade_out: 0.2,
                        mute: false,
                        duck: false,
                      },
                    ],
                    settings: { ...value.settings, audio_mode: "mixed" },
                  })
                }
              >
                Add {a.metadata.original_name || a.id.slice(0, 8)}
              </button>
            ))}
        </div>
        {value.audio.map((t: any, i: number) => (
          <article className="audio-edit" key={t.id}>
            <AudioWaveform assetId={t.asset_id} />
            <div className="settings-grid">
              <label>
                Track
                <select
                  value={t.role}
                  onChange={(e) => audio(i, { role: e.target.value })}
                >
                  {["music", "voiceover", "effects"].map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </label>
              {[
                ["start", "Position in movie"],
                ["trim_in", "Source in"],
                ["trim_out", "Source out"],
                ["volume", "Volume"],
                ["fade_in", "Fade in"],
                ["fade_out", "Fade out"],
              ].map(([key, label]) => (
                <label key={key}>
                  {label}
                  <input
                    type="number"
                    min={0}
                    step={0.1}
                    value={t[key] ?? 0}
                    onChange={(e) =>
                      audio(i, { [key]: Number(e.target.value) })
                    }
                  />
                </label>
              ))}
              <label>
                <input
                  type="checkbox"
                  checked={!!t.mute}
                  onChange={(e) => audio(i, { mute: e.target.checked })}
                />{" "}
                Mute track
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={!!t.duck}
                  onChange={(e) => audio(i, { duck: e.target.checked })}
                />{" "}
                Lower music during voiceover
              </label>
            </div>
            <button
              className="button"
              onClick={() =>
                change({
                  ...value,
                  audio: value.audio.filter((_: any, n: number) => i !== n),
                })
              }
            >
              Remove track
            </button>
          </article>
        ))}
      </details>
      <details>
        <summary>Export picture, transitions & loop</summary>
        <div className="settings-grid">
          <label>
            Picture size
            <select
              value={`${value.settings.width}x${value.settings.height}`}
              onChange={(e) => {
                const [width, height] = e.target.value.split("x").map(Number);
                change({
                  ...value,
                  settings: { ...value.settings, width, height },
                });
              }}
            >
              {["640x352", "1280x720", "1920x1080", "3840x2160"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          {["fps", "crf", "repeats", "transition_duration"].map((k) => (
            <label key={k}>
              {
                (
                  {
                    fps: "Frames per second",
                    crf: "Quality CRF (lower is better)",
                    repeats: "Loop repetitions",
                    transition_duration: "Transition seconds",
                  } as any
                )[k]
              }
              <input
                type="number"
                step={k === "transition_duration" ? 0.05 : 1}
                value={
                  value.settings[k] ?? (k === "transition_duration" ? 0.35 : 1)
                }
                onChange={(e) => config(k, Number(e.target.value))}
              />
            </label>
          ))}
          {Object.entries({
            codec: ["h264", "h265"],
            fit: ["pad", "crop"],
            audio_mode: ["silent", "preserve", "mixed"],
            transition: ["cut", "fade", "fade_black", "dissolve"],
            loop: ["none", "continuous", "fade_black", "crossfade"],
          }).map(([k, options]) => (
            <label key={k}>
              {k.replaceAll("_", " ")}
              <select
                value={value.settings[k]}
                onChange={(e) => config(k, e.target.value)}
              >
                {options.map((o) => (
                  <option key={o}>{o}</option>
                ))}
              </select>
            </label>
          ))}
        </div>
        <p className="muted">
          Crossfades shorten the movie by their overlap. Loop blending cannot
          guarantee matching subjects at the boundary. Export a preview to
          inspect the final-to-first transition.
        </p>
      </details>
      <div className="button-row">
        <button
          className="button"
          disabled={dirty || !value.clips.length}
          onClick={() =>
            act(
              () => request(`/api/projects/${project.id}/preview`, {}),
              "Editing preview queued with exact transitions and sound. Find it in Exports.",
            )
          }
        >
          Render saved preview
        </button>
        <button
          className="button primary"
          disabled={dirty || !value.clips.length}
          onClick={() =>
            act(
              () => request(`/api/projects/${project.id}/export`, {}),
              "Frozen movie export queued.",
            )
          }
        >
          Export saved timeline
        </button>
        <label>
          Restore a saved version
          <select
            value=""
            onChange={(e) => {
              if (e.target.value)
                act(
                  async () =>
                    adopt(
                      await request(
                        `/api/projects/${project.id}/timeline/restore/${e.target.value}`,
                        {},
                      ),
                    ),
                  "Timeline restored as a new revision.",
                );
            }}
          >
            <option value="">Choose timeline revision</option>
            {history.data
              ?.filter((h) => h.revision !== revision)
              .map((h) => (
                <option key={h.revision} value={h.revision}>
                  Revision {h.revision}
                </option>
              ))}
          </select>
        </label>
      </div>
    </section>
  );
}
