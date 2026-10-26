# Verification ledger

## Phase 1 — Foundation

- Published commit `d65ccc8`; GitHub Actions run `40386284221` passed backend tests, frontend build and Pages deployment.
- Ten automated foundation tests passed locally and in CI: private API rejection, hostile origins/hosts, project reopening, immutable revisions, revision conflicts, project isolation, revocation, pairing-code reuse rejection, service URL restrictions and authenticated event-ticket creation.
- The real HTTPS Pages interface paired with the loopback agent and displayed the existing local project, actual GPU measurements, ComfyUI version and installed Ollama model names in the in-app Chromium browser. This is not yet a claim of independent Edge/Chrome permission grant/deny testing.

## Phase 2 — Image-first production

- Twenty automated foundation/production tests passed locally. The production fixture includes twenty independent scenes, future-scene edits during a separate active job, immutable active inputs, duplicate batch prevention, source-still requirements, independent review gates, manual/automatic policy preservation, frozen mappings and unsafe output-path rejection.
- A real UI-triggered Qwen Image 2.1 INT8 generation produced a decoded 640×352 PNG. ComfyUI reported 110.79 seconds.
- That exact still was explicitly approved and selected in the UI. A real UI-triggered Wan 2.2 I2V-A14B FP8 job produced a 640×352 H.264 video, 81 decoded frames at 16 fps, duration 5.0625 seconds, no audio. The video asset records its source still ID and matching SHA-256 hash.
- Both Studio browser tabs were closed during animation. The local agent completed collection and validation independently. The render finished shortly before an intentional agent restart; restoring completed work is verified, but this particular run does not prove restart recovery of an actively running render.
- A partial preview was deliberately built from the one completed scene, leaving the other seven unfinished. FFmpeg 9.0.2 normalized the clip to 1920×1080, 30 fps, H.264; FFprobe and a full decode verified 152 frames, 5.066667 seconds and no audio. The export is explicitly labeled partial, not a completed eight-scene movie.
- Private manifests, job IDs, prompts, source hashes, media and operational logs remain in the local installation and are excluded from this repository.

## Still required before completion

Active-render restart reconciliation; accepted-before-response submission recovery; full AI Director planning and safe proposal application; automatic multi-scene production; optional vision QA and bounded regeneration; richer timeline/audio transitions; synthetic export-order tests; backup/restore; workflow import mappings; standalone Edge/Chrome local-network permission cases; final accessibility and release audit. Later phases will add evidence here rather than treating planned tests as passed.
