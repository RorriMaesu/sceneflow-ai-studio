# SceneFlow AI Studio: optimized delivery plan

## Product and constraints

A private local filmmaking workspace with a public static React interface. The Windows agent is authoritative for projects, revisions, jobs, media, hardware scheduling, and exports. GitHub receives application source only. Media, pairing secrets, databases, logs, personal prompts and model files never enter the repository.

Hybrid Assisted Autopilot is the default. Autopilot and Manual are policies over the same engine. AI visual QA is off by default. Every ordinary video generation requires an explicitly identified still first. Missing capabilities remain unavailable, with an explanation.

## Delivery phases

1. **Foundation and connection:** premium responsive interface, project/scene persistence, revisions, authenticated pairing, exact origin/host validation, local frontend fallback, isolated M: environment and one-click launcher. Publish the first functional Pages build.
2. **Durable Manual production:** verified ComfyUI adapters, image-first jobs, explicit asset selection, immutable manifests, exact output collection, dependency scheduler, recovery, media playback, and a real still-to-video-to-MP4 test. Publish.
3. **Direction and automation:** real Ollama discovery and structured planning, safe proposed edits, resource coordination, three-mode switching, review gates, Auto Produce, and live intervention. Prove a 20-scene simulated production and real multi-scene generation. Publish.
4. **Editing and assembly:** candidate/take review, timeline reorder/trim/split/speed, sound tracks, transitions, loop options, export snapshots, provenance, backup/restore and project bundles. Verify using synthetic labeled clips and real generated footage. Publish.
5. **QA and release verification:** optional installed vision models, frame sampling, technical checks, bounded retries, mapping editor, capability explanations, accessibility/browser checks, onboarding, diagnostics and a complete evidence ledger. Publish the release.
6. **Creative continuity:** owned visual references and locked style rules, reference-conditioned stills, source-latent masked correction, before/after review and exact pixel-preservation checks. Prove a four-shot film and publish.
7. **Editing and production control:** continuous shared playhead, waveform/trim controls, exact rendered previews, bounded run budgets and attempts, measured timing ranges and persisted reviewed Director commands. Prove paused-project editing and sound; publish.
8. **Keyframes and studio care:** native first/last conditioning with existing weights, end-image backup/hash checks, reversible scratch quarantine, optional tray controls and opt-in notices. Prove another actual video and publish. LTX model installation is deferred by user choice.

Each phase has a source commit, a visible release label and a successful GitHub Pages deployment. A phase is not complete merely because a deployment workflow started.

## Architecture

React + TypeScript + Vite, accessible custom components, Motion, dnd-kit, Zustand and TanStack Query. FastAPI + Pydantic + SQLite (explicit transactions and migrations), one background dispatcher, HTTP/WebSocket clients, FFmpeg/FFprobe, Pillow and NVML with a labeled fallback.

Modules: configuration/security, storage/revisions, API, workflow adapters and registry, ComfyUI/Ollama clients, production scheduler, resources, media/export, and testing. Use an isolated Python environment; never install into ComfyUI's Python. All substantial storage and caches live under M:/AI-Video-Studio.

## Critical invariants

- Stable UUIDs identify projects, scenes, scene revisions, attempts, jobs, assets and exports. Human titles never determine ownership.
- Job inputs are immutable. Editing pending work supersedes jobs; editing active work saves a new revision. Operational updates never overwrite creative revisions. Conflicting edits return HTTP 409.
- A video's source still ID and hash remain permanently associated with that attempt. Approvals belong to specific assets. New selections cannot relabel older takes.
- Persist an attempt before submission and include its ID in ComfyUI metadata. A failed submission response enters reconciliation, not blind retry. Reconcile queue/history before any restart recovery resubmission.
- One dispatcher and transactional claiming prevent duplicate work. A global resource lease covers planning, diffusion and vision QA. Foreign ComfyUI work is observed, never cancelled or freed.
- Review gates affect only dependent work. Independent scenes continue. Manual mode stops new automatic launches after the active job; switching modes preserves history and approved assets.
- Timeline order is independent of render order. Started exports freeze timeline revision, assets, trims, transitions, audio and settings. Later edits make that export outdated.
- Validate media by decoding/probing and collect only exact prompt/output-node results. Commit assets with atomic writes and hashes. Incomplete files never become valid assets.

## Security and browser connection

Loopback binding only, exact Host/Origin checks, short-lived local pairing codes, random revocable bearer sessions and validated typed mutations. No wildcard CORS. WebSockets use one-use short-lived tickets. Media uses asset-scoped expiring tickets and Range requests; no unauthenticated project directory mount. Tokens and media tickets are excluded from access logs.

GitHub Pages origin is https://rorrimaesu.github.io (repository paths are not origins). Modern Edge/Chrome local-network permission is independent of CORS. Test the published site against local APIs and media; provide a same-origin agent-served fallback and actionable permission guidance. Never weaken browser security policies. Remote access stays disabled.

Imported workflows are a trust boundary: validate API-format graphs, registered node types, required files, mappings, size constraints, output nodes and workflow hashes. Do not install custom nodes or execute arbitrary AI commands. Model discovery and generation verification are distinct states.

## Gaps added to the original brief

Submission ambiguity; single-agent enforcement; idempotency keys; stale revision conflicts; file path/reparse-point containment; authenticated video ranges; session revocation; workflow trust; immutable exports; rational time/frame handling; disk headroom for intermediate files; external workload ownership; bounded AI context; evidence-backed readiness; explicit partial exports; portable restoration; and a requirement-to-test ledger.

## Evidence and acceptance

Automated tests cover authentication, hostile origins/hosts, traversal, scene isolation, out-of-order results, unknown submissions, restart reconciliation, active-edit snapshots, mode transitions, gates, foreign jobs, bounded retries, QA-disabled behavior, timeline ordering and synthetic audio/video exports. Live tests cover installed Ollama, Qwen still generation, Wan animation from that exact still, final export, browser reconnect and actual published Pages connectivity. Optional absent workflows are documented as unsupported rather than simulated.

Prior Wan success is baseline evidence only; new Studio jobs must independently prove the entire pipeline. 720p generation is not assumed safe. Begin with the measured 640×352/49 and 832×480/81 Wan presets.
