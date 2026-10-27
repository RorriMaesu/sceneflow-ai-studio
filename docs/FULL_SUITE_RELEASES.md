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

## Remaining phases

14: shared resource broker and provider isolation. 15: script lines/cast voices and real speech. 16: music/effects. 17: shows/films and shared continuity. 18: music-video timing, lip-sync and captions. 19: long-form sequences and resumable assembly. 20: conditional LTX and staged updates. These are not claimed as delivered by Phase 13.
