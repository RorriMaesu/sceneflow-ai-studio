# Verification ledger

## Phase 1 — Foundation

- Published commit `d65ccc8`; GitHub Actions run `40386284221` passed backend tests, frontend build and Pages deployment.
- Ten automated foundation tests passed locally and in CI: private API rejection, hostile origins/hosts, project reopening, immutable revisions, revision conflicts, project isolation, revocation, pairing-code reuse rejection, service URL restrictions and authenticated event-ticket creation.
- The real HTTPS Pages interface paired with the loopback agent and displayed the existing local project, actual GPU measurements, ComfyUI version and installed Ollama model names in the in-app Chromium browser. This is not yet a claim of independent Edge/Chrome permission grant/deny testing.

## Phase 2 — Image-first production

- Published commit `8a5bb63`; GitHub Actions run `40391134319` passed tests, build and Pages deployment. The published HTTPS page displayed and played the authenticated local movie preview.

- Twenty automated foundation/production tests passed locally. The production fixture includes twenty independent scenes, future-scene edits during a separate active job, immutable active inputs, duplicate batch prevention, source-still requirements, independent review gates, manual/automatic policy preservation, frozen mappings and unsafe output-path rejection.
- A real UI-triggered Qwen Image 2.1 INT8 generation produced a decoded 640×352 PNG. ComfyUI reported 110.79 seconds.
- That exact still was explicitly approved and selected in the UI. A real UI-triggered Wan 2.2 I2V-A14B FP8 job produced a 640×352 H.264 video, 81 decoded frames at 16 fps, duration 5.0625 seconds, no audio. The video asset records its source still ID and matching SHA-256 hash.
- Both Studio browser tabs were closed during animation. The local agent completed collection and validation independently. The render finished shortly before an intentional agent restart; restoring completed work is verified, but this particular run does not prove restart recovery of an actively running render.
- A partial preview was deliberately built from the one completed scene, leaving the other seven unfinished. FFmpeg 9.0.2 normalized the clip to 1920×1080, 30 fps, H.264; FFprobe and a full decode verified 152 frames, 5.066667 seconds and no audio. The export is explicitly labeled partial, not a completed eight-scene movie.
- Private manifests, job IDs, prompts, source hashes, media and operational logs remain in the local installation and are excluded from this repository.

## Phase 3 — Direction and automation

- Twenty-six automated tests pass. Added typed proposal transactions, stale/foreign-scope rejection without partial edits, structured JSON correction limited to one retry, bounded Director context, and exact reconciliation of an accepted submission whose response was lost. Recovery tests assert that no second POST occurs.
- A twenty-scene simulation completed forty image/video stages with distinct scene inputs, immutable snapshots and the correct source-still link for every video. This simulation uses placeholder assets and is a scheduler test, not a claim of forty real generations.
- The actually installed `gemma4:12b` model produced and validated a two-scene plan through local Ollama. Studio applied it to an empty Automatic project, confirmed unloading the model, then generated two real Qwen stills and two real Wan animations, selected technically valid outputs and automatically exported the complete two-scene movie.
- During the first real still render, the owned Studio agent was stopped and restarted. It reattached to the same ComfyUI prompt ID and collected its output; no replacement render was submitted.
- During the first scene's real video render, the second scene's pending motion prompt was edited. Only that pending job was superseded. Its replacement preserved the selected still ID; the active job's saved inputs were byte-for-byte unchanged. Both scene videos and final assembly completed.
- Added independent planning/image/video selectors, candidate count, editable Hybrid review gates, planning approval, pending priority/cancellation, frozen-input inspection, and one-use pairing code creation for another browser.

## Phase 4 — Editing, sound and portability

- All 34 backend tests passed locally, including eight new FFmpeg/backup integration tests. With the large example generating at the same time on the shared project drive, the full run took 14 minutes 26 seconds; the media-only run took 36 seconds. These are observed test timings, not generation estimates.
- Labeled red/green/blue clips verified playback order by decoded pixel colors even after the saved timeline changed. Export snapshots retained the originally queued order. Output audio was verified as a single 48 kHz stereo track.
- Fade, fade-through-black, dissolve, two repeated loops, crossfaded loop boundaries and explicitly silent variants passed probe and full-decode checks. The tests caught and fixed FFmpeg 9 filter-file syntax and AAC padding affecting repeated-loop frame timing.
- Imported music and voiceover passed trims, placement, volume, fades and music ducking tests. Modified source bytes blocked frozen exports. Re-executing the same completed export did not create duplicate assets.
- Project bundle restore verified fresh project/scene/asset identifiers, media hashes, original-project preservation and a paused restored project. Traversal entries were rejected before writing outside restore storage.
- The real browser split a generated clip, saved a new timeline revision and restored the earlier cut as a further revision. Media controls, source trims, replacement takes, split/duplicate/remove, reorder, local undo/redo and export settings are available in the editor.
- The complete two-scene real movie is 1920×1080 H.264, 30 fps, 124 decoded frames, 4.133333 seconds, explicitly silent. The eight-scene example is running separately; its completed movie will be recorded only after it finishes.

## Still required before completion

Optional vision QA and bounded regeneration; standalone Edge/Chrome local-network permission cases; final accessibility and release audit. Later phases will add evidence here rather than treating planned tests as passed.
