# Full studio implementation

This ledger distinguishes delivered work from planned phases. New models are not Ready merely because they appear in the library.

## Phase 13 — Guided setup and verified downloads

- A dedicated Setup & downloads screen offers recommended folders or the Windows folder picker, plus optional per-media folder choices. Existing project files remain readable in their old locations.
- Registered roots retain volume identity and reject path traversal, linked boundaries and missing/replaced drives. Images, clips, music, speech, effects, exports, backups and provider caches have separate routes. Export scratch remembers its original location across later folder changes.
- Pinned official model packs include exact byte sizes and SHA-256/Git blob checksums. Quotes are bound to the reviewing session, pack revision and folder. Corrupt existing files count in the quote. Downloads are serialized, resumable, bounded by reviewed size and free space, and pause on revocation/restart. Hash failure never installs a model.
- Downloads never execute model support code or replace the existing ComfyUI runtime. Downloaded files remain Needs a test until isolated runtime setup and inference qualification are completed in later phases. LTX remains deferred and cannot be installed by this screen.
- Metadata update checks do not replace working tools. Runtime environments point caches to the selected folder and disable implicit inference-time downloads.
- Existing sound imports and visual workflows remain available. The setup screen permits finishing with existing tools without mandatory new model downloads.

Validation: the full local suite passed 103 backend checks before three additional storage/download cases; the focused final setup suite passed 19 checks. Frontend's 14 checks and its production build passed. CI runs the combined final suite. Live setup/browser proof is recorded with the deployment.

Phase 13 was published as `6d1525d6fb857e5f0ae4a4eedd11a0033ac4bf2a`; [all checks and deployment passed](https://github.com/RorriMaesu/sceneflow-ai-studio/actions/runs/40559989506). Live local setup exposed the correct destinations, exact quotes and deferred LTX state. The user subsequently approved the three initial model packs; their private download transactions are excluded from source.

## Phase 14 — Shared memory protection and isolated worker boundary

The dispatcher now acquires a named device lock and a durable GPU reservation before loading graphics models. A dead process or expired timestamp does not clear uncertain backend work: the original task must be reconciled. External ComfyUI/Ollama sessions are preserved. Admission checks live GPU memory, physical RAM, Windows commit headroom and a graphics reserve; observed sampled peaks are retained with their limitations.

New providers have a subprocess boundary with registered runtime paths, frozen request hashes, result ownership nonces and managed output checks. Cancellation verifies PID creation time, executable and exact input marker, rather than stopping processes by name. Concrete speech/music/effects runtime installation and generation are later phases; this boundary alone does not enable those models.

The setup flow now reveals optional tools on demand, focuses the download review after selection, and displays the shared memory policy. Finishing setup does not claim a disconnected creation service is ready.

Validation: 120 backend checks passed locally with FFmpeg/FFprobe available and test scratch on the media drive. Fourteen frontend checks passed in the preceding setup phase; the final interface build passed. The named-lock test uses a real competing process. Worker tests verify stopping the exact owned process and preserving a mismatched/reused PID. Live inference and CI evidence accompany this phase's publication.

## Remaining phases

15: script lines/cast voices and real speech. 16: music/effects. 17: shows/films and shared continuity. 18: music-video timing, lip-sync and captions. 19: long-form sequences and resumable assembly. 20: conditional LTX and staged updates. These are not claimed as delivered by Phase 14.
