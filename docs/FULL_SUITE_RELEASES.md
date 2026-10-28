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

## Phase 15 — Private runtimes, script lines and preset voices

Pinned Windows/Python 3.12 runtime recipes install into registered media storage with verified package hashes and separate environments. The reviewed setup transaction is session-bound; retries reuse the package cache. Program imports alone never qualify a model. Setup now offers program setup, sample creation and listening as separate, plain-language actions.

Story and Edit expose characters, preset voices, script lines, language, recording and placement. Line revisions retain old recordings; a result from an earlier script revision cannot silently become the current line. Sounds are placed explicitly, and export uses the existing 48 kHz mix/ducking pipeline. Voice cloning and acting instructions are not advertised for the small preset voice pack.

Actual local Qwen3-TTS speech completed through the shared GPU queue and passed full audio decoding. Eight focused checks passed for script history, cross-production ownership, unsafe source archives, setup-only archived jobs, readiness gates, unsupported delivery instructions, session-bound approval and cancellation. The interface production build passed. Music and effects adapters are included for qualification in Phase 16; they remain gated by their own samples.

Phase 15 was published as `5e11299bb08fe43547cf0c0c68916ae78c52109c`; [verification and Pages deployment passed](https://github.com/RorriMaesu/sceneflow-ai-studio/actions/runs/40569947292).

## Phase 16 — Music, songs, effects and a recorded conversation

Actual local tests completed for Qwen3-TTS speech, an ACE-Step instrumental, a short vocal song and a MOSS rain effect. The small effects profile uses only the requested latent duration, CPU offloading and floating-point weight conversion that preserves complex positional buffers. An earlier default configuration reached the allocator ceiling; it was stopped, corrected and retested. Existing ComfyUI packages were preserved throughout.

Device-wide sampled GPU peaks were approximately 3.4 GiB for speech, 6.1 GiB for music and 4.5 GiB for the corrected effects test. These observations include other apps and are not guaranteed maxima. Music also used substantial system memory; future admission includes measured growth plus allowance. A per-worker allocator ceiling and one shared GPU queue provide additional limits.

The private proof contains two recurring preset voices across three lines, real recorded timing with short pauses, generated background music and generated rain, assembled over previously generated visual footage. It demonstrates the new sound path rather than claiming newly generated lip-sync or a full new film. Each tool stays bounded by its passed duration; singing is a separate setup check. Users can listen before placing any take.

Sound forms and script edits protect browser drafts. Backups now include casts, lines and revision history, restore under new IDs and keep work paused; bundles with script data use version 2 so older agents reject them safely. Duplicate clicks reuse queued sound requests. Thirteen focused sound/history/backup checks and the production interface build passed locally. CI runs the full regression suite before Pages deployment.

Phase 16's complete suite passed after the restart recovery correction in `e6d25ac480b8c156949bd4b139e1334dc31e61e2`; [verification and Pages deployment passed](https://github.com/RorriMaesu/sceneflow-ai-studio/actions/runs/40575540757). The mixed proof fully decoded: 20 seconds, 1920×1080, 30 fps, 600 frames, stereo 48 kHz sound, five mixed sound tracks.

## Phase 17 — Shows, films, chapters and shared continuity

The creation wizard now distinguishes short videos, shows, movies and music videos. A production contains numbered seasons/episodes or parts/chapters, each with one or more bounded sequence projects. Existing project IDs and media stay usable. Sequence projects are grouped under their production rather than duplicated as standalone home cards.

The Director can propose up to 24 connected episodes/chapters in one bounded outline. Applying a reviewed outline creates empty sequences only. Shared canon, episode start/end states and their revisions enter subsequent scene-planning context. Episode edits and canon saves use revision checks; active jobs keep frozen context. Cast membership comes from database relationships, so sibling episodes share a voice library without allowing unrelated productions to borrow it accidentally.

A real local three-episode outline was generated, reviewed in the browser and applied. All three sequences had zero footage/sound jobs and zero assets; the same cast ID was visible across the three episodes. Six final planning checks passed, including stale outlines, duplicate episode numbers, shared cast with separate scripts, ownership boundaries and revision-protected episode edits. The earlier combined 18-check sound/planning/restart run passed. The production interface build and full CI accompany publication.

## Phase 18 — Song masters, sections and captions

Music-video productions share a hash-locked original song. Editable section markers and bounded visual planning respect that source. Fitting visuals trims the saved edit to a frame-rounded song duration, uses straight cuts and plays once; it refuses insufficient visuals or speech/effects extending past the song. The original recording and earlier takes remain intact. Song settings, assignments, caption edits and history survive version-3 portable backups.

The approved private caption runtime uses current native Transformers support for pinned Qwen3-ASR and ForcedAligner models. Recognition processes bounded 30-second chunks and releases its model before spoken-word alignment loads. The first test is at most 30 seconds; longer recognition supports sources up to 30 minutes. Known-speech alignment supports short spoken clips in nine languages. Singing gets rough recognition ranges and manual correction, not certified word alignment. Recognized drafts never overwrite a saved caption edit automatically.

Users can write captions, import SRT/VTT, reuse recorded-script line timing, review recognized words, download separate subtitles or include a selectable MP4 caption track. Browser drafts are protected; export refuses unapplied caption drafts. The actual 20-second mixed sound proof yielded all three spoken lines through the music and rain, with real word timestamps and pauses separating the lines. Its captioned export and subtitle files are kept private.

Validation: 25 focused sound/caption/backup checks passed before the final exact-song-fit case; the final caption suite and interface production build accompany publication. Lip-sync was not installed or qualified; face and singing mouth animation are explicitly unavailable. The approved caption download does not include those separate models. LTX remains deferred.

## Remaining phases

19: long-form sequences and resumable assembly. 20: simplified setup and staged updates. Conditional LTX testing remains skipped at the user's request. These are not claimed as delivered by Phase 18.
