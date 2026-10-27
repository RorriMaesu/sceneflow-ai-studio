# Requirements and capability coverage

| Request group | Delivered behavior | Evidence / boundary |
| --- | --- | --- |
| Hardware, storage, architecture (1–3, 15, 20–21) | Isolated environment on the project drive; Pages frontend; authenticated loopback agent; SQLite; dispatcher; actual telemetry; process-local startup | Real Pages pairing and generation; owned-agent restart recovery; existing ComfyUI preserved |
| Workspace and design (4, 16, 22, 24) | Dark responsive workspace, scene inspector, drafts/revisions, search, keyboard controls, timeline history and diagnostics | Browser checks and reduced-motion styling; standalone Edge/Chrome permission cases unverified |
| Selectors and registry (5–6, 10) | Independent planning/image/video selectors and QA selector; mappings, limits, discovery and generation evidence | Real Qwen/Wan outputs; imported graphs require explicit media mappings and runtime verification |
| Director and planning (7–8, 36) | Bounded context, structured validation, one corrective retry, larger-plan batching, typed proposals and atomic scope checks | Real installed Gemma two-scene plan; stale/foreign proposal tests |
| Still-first lineage (9, 12–13, 40) | Exact still IDs/hashes, UUID paths, immutable attempts, scoped collection, takes and dependency invalidation | Real still-to-video proofs; out-of-order/partial collection; frozen mappings and hash rejection |
| Scheduler and modes (14, 30–33, 37–38) | Automatic, Hybrid default and Manual over one engine; independent gates; persistent queue; pause, retry, priority, scoped cancel and live edits | Twenty-scene simulation; real automatic two-scene film; future-scene edit during active animation |
| Audio (11, 18–19) | Silent/preserved/mixed sound, music/voice/effects, placement, trims, fades, ducking and exact-job sidecars | Synthetic audio integration tests; local LTX generation unconfigured |
| Timeline and loops (18–19) | Explicit playback order; trim/split/duplicate/remove/speed/replacement; cuts/fades/dissolves; loops; frozen exports | Pixel-labeled order test; browser split/save/restore; full decode/probe; real eight-scene loop movie |
| Backup and recovery (23–24) | Bundles, hash checks, new IDs, paused restores, quarantine, path/reference checks and private diagnostics | Media-backed restore tests; traversal rejection; original project preserved |
| References and correction (9, 12) | Visual bible, up to three owned image references, immutable hashes, masked source-latent correction, brush undo/zoom, before/after and candidate comparison | Four real reference stills; refined local correction; unchanged outside-mask pixels verified |
| Optional QA (34–35, 39) | Off by default; local vision discovery; sampled frames; separate technical results; bounded retries; manual precedence; contradictory-advice guard | Real still and three-frame video reviews; simulated retries/overrides; advisory scores |
| Advanced workflows (11–12, 17) | Capability explanations and guarded import mechanism | LTX audio/conditioning, ending-keyframe controls, outpainting, neural upscaling and specialized video editing require separate configuration/verification |
| Delivery (25–29) | Source, setup/start/stop scripts, deployment, tests, architecture, evidence and troubleshooting | Private two-scene proof and complete eight-scene movie; per-phase Pages deployments |

Installed filenames, ready graphs, AI scores and started deployments are kept distinct from successful generation and verified releases.

Primary references: [Ollama structured outputs](https://docs.ollama.com/capabilities/structured-outputs), [Ollama chat](https://docs.ollama.com/api/chat), [FFmpeg filters](https://ffmpeg.org/ffmpeg-filters.html). The local ComfyUI source was inspected for atomic per-job cancellation.
