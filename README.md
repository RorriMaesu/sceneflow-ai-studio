# SceneFlow AI Studio

A local filmmaking studio for planning scenes, generating starting stills, animating their exact images, reviewing takes and assembling a movie. The public React interface connects to an authenticated Windows agent on your computer.

**Release 0.17 — shows, movies and shared story planning.** Create a short video, series, movie or music video. A production holds seasons/episodes or chapters and manageable sequences. Episodes share a cast and story guide while keeping their scenes and edits separate. The local Director can propose a whole season for review without starting footage. Speech, music and effects remain available through the qualified sound workflow. [Full studio release ledger](docs/FULL_SUITE_RELEASES.md). LTX remains deferred.

- [Published interface](https://rorrimaesu.github.io/sceneflow-ai-studio/)
- [Verification ledger](docs/EVIDENCE.md)
- [Optimized build plan](docs/BUILD_PLAN.md)
- [Requirements coverage](docs/REQUIREMENTS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)

The completed local proof includes an eight-scene, 26.533333-second H.264 movie: 1920×1080, 30 fps, 796 decoded frames, silent, with a fade-through-black loop boundary. Source animation was generated at 640×352 and scaled during assembly. Private movies and production data are excluded from Git.

## Open this installation

Choose **Create a video**, describe your idea and select an approximate length and shape. Assisted is recommended. The local Director can propose scenes for your review; creating a project does not start photo/video generation. Follow the five project steps and use **Save video → Create finished video → Download MP4** when your edit is ready. Advanced tools remain available under Settings and each video's advanced controls.

Scene, story, look, project-setting and timeline drafts remain in the browser where you edited them until saved or discarded. Finishing blocks an unapplied timeline draft. Saving applies a new revision to the local studio; active renders keep their original inputs and earlier media remains available. A full novice-user study has not yet been conducted.

Open `M:\AI-Video-Studio\START_STUDIO.bat`. It starts available local services, starts or reconnects the owned agent, creates a one-use pairing code and opens the private interface. Production continues after the browser closes. `STOP_STUDIO.bat` stops this agent; saved generation jobs can reconnect on the next launch.

The Pages interface uses the same local data. Enter the launcher's code, or create one under **Settings → Create code for another browser**. Codes expire after ten minutes and are consumed once. Paired sessions last seven days and can be revoked in Settings.

## Install another checkout

1. Put the source on a drive with sufficient space, such as `M:\AI-Video-Studio`.
2. Install Python 3.11 and Node.js 24. Run `SETUP_STUDIO.bat` to create the isolated environment, install pinned dependencies and build the interface.
3. Keep the existing ComfyUI installation and models. Default services are `http://127.0.0.1:8188` and local Ollama at `http://127.0.0.1:11434`.
4. Put portable `ffmpeg.exe` and `ffprobe.exe` under `tools/ffmpeg/`. This machine has the verified FFmpeg 9.0.2 essentials bundle from the Windows builds linked by [FFmpeg](https://ffmpeg.org/download.html). Tools and model weights are not bundled in Git.
5. Run `START_STUDIO.bat`, pair the browser, refresh discovery in Model Library and choose installed models independently.

The launcher uses process-local settings. Defaults recognize `M:\ComfyUI\run_nvidia_gpu.bat` and `M:\AiStudio\OllamaModels`. Other installations can set `comfy_launcher`, `ollama_models`, `auto_start_comfy` and `auto_start_ollama` in private `config/settings.json`. Existing services are reused. Setup preserves ComfyUI's Python, packages and models.

A browser may ask for local-network permission. The agent-served interface at `http://127.0.0.1:8770` provides a same-origin fallback. Independent Edge/Chrome permission grant, deny and revoke cases remain unverified in this session because those browsers were unavailable to the test tools.

## Production modes

**Assisted / Hybrid** is the default. Review stills, video takes and the timeline at independent checkpoints. Other scenes can continue while a review waits. Storyboard and prompt reviews can also be enabled.

**Autopilot / Automatic** plans empty projects when a planning model is selected, reuses compatible work, chooses technically valid takes according to its settings and assembles the movie after reviews are clear. Without visual QA, selection uses technical acceptance.

**Manual** provides explicit planning, generation, selection and export commands. Mode changes retain revisions, attempts and assets. Active renders keep frozen inputs. Pending work is updated only for affected scenes and stages.

Scene drafts stay in the browser until saved or discarded. Revision conflicts require a refresh. The Director presents typed proposals that apply atomically after review: scene creation, targeted prompt changes and style-guide edits. Operational controls remain explicit.

The Director can also propose duration, seed and installed-workflow changes. Generation, visual-review and queue proposals require the explicit **Include generation and queue command proposals** opt-in, followed by proposal approval. Creative-only requests use a narrower schema. Setting fields cannot be disguised as generation operations. Reviewed operations persist until a dispatcher boundary, retain exact target revisions and fail safely if the target or project settings changed.

Production settings expose attempts per new video stage, zero-to-two quality retries, an elapsed run budget and failure policies. Budgets include waiting and stop before a new automatic job; active jobs finish. Resume starts a new budget window. Explicit scene work, review and exports preserve the paused state of other production. Partial exports respect review gates and preserve manually edited cuts.

## Editing and sound

The timeline supports drag/button reordering, trims, speed, duplicate/split/remove, replacement takes, local undo/redo and saved-revision restoration. Playback order is independent of generation order. Exports freeze the timeline and verify source hashes.

The shared playhead previews the current draft continuously with cuts and approximate browser audio levels. It supports seeking, snapping to clip boundaries, direct trim sliders and imported-audio waveforms. **Render saved preview** makes a smaller H.264 movie with the exact saved transitions, loops and sound mix, without changing final export settings or resuming paused generation.

Sound can be discarded, preserved or mixed with imported music, voiceover and effects. Controls include placement, trims, volume, mute, fades and music ducking. Generated audio sidecars share the exact scene and job and are included once.

Exports include H.264/H.265, pad/crop fitting, configurable size/frame rate, cuts/fades/dissolves, repeated loops and boundary blending. FFprobe and full decoding verify output. Loop blending cannot establish seamless scene continuity.

## Optional visual QA

**AI Quality Control starts off.** Its model is independent and must advertise local vision capability. Reviews can run automatically, manually, on selected candidates or on suspicious outputs.

New video reviews inspect seven evenly spaced samples and the saved visual references. Actual sampled frames can be opened without AI inference. Technical measurements are separate from advisory visual scores; samples cannot establish complete motion adherence or sound quality. The tested model returned conflicting high scores and regeneration advice; the interface flags contradictions for human review and prevents them from triggering regeneration.

Quality retries require an actionable low-scoring failure, preserve earlier attempts, stop without improvement and are limited to two per stage. Manual approval takes precedence.

Acceptance advice with low confidence, low component scores or a high-severity issue also requires human review. A review can request a creative-only Director correction proposal; it does not directly change prompts or start generation.

Observed timing ranges use matching completed presets and explicitly exclude unmeasured work, active jobs, reviews and waits. Draft/20-step/25-step presets and experimental higher resolution remain distinct from measured quality guarantees. Browser completion notifications are optional and require permission; they work while the browser remains open. An interface recovery screen reconnects to saved local work after a rendering error.

## Workflow limits

Verified native adapters: Qwen Image 2.1 INT8 and Wan 2.2 I2V A14B FP8 with the existing four-step Lightx2v LoRAs. The measured Studio baseline is 640×352 at 16 fps, up to 81 Wan frames. Registry limits do not guarantee that every larger preset fits memory.

The advanced editor imports API-format workflows with validated mappings, installed nodes/model choices, output nodes and conservative limits. Every image loader must map to the registered source still. Static reference media, audio conditioning and unapproved node classes require a separately verified adapter.

The visual bible selects up to three project-owned reference images and locked appearance rules. Qwen reference generation uses those exact files and verifies their hashes before submission. A scene can override references through its saved settings. Changing references or rules invalidates affected pending inputs while active jobs and old takes remain intact.

The correction canvas supports zoom, brush masks, erasing, brush undo, strength and step controls, and before/after comparison. Masked correction uses source-encoded Qwen latents with a noise mask, then composites against the original and rejects any change outside zero-mask pixels. Corrections remain unselected takes until approved. Supported target dimensions are multiples of 32 up to 2048 pixels; hardware capacity remains preset dependent.

Scene **Settings → Starting & ending frames** accepts an optional owned project image. The native Wan first/last adapter reuses the installed weights, freezes both image IDs/hashes, and invalidates only animation inputs when the ending changes. The starting still can also be the ending target for loop guidance. Conditioning cannot guarantee exact ending pixels or a seamless loop.

LTX synchronized generation was deferred at the user's request. Outpainting, neural upscaling and specialized video-editing models remain unconfigured. Large models and custom nodes are never downloaded automatically. Masked correction currently requires an opaque still so preservation includes the full visible source.

## Optional tray and studio care

Run `START_TRAY.bat` for a Windows notification-area menu. It opens the studio, stops only the owned agent, or exits the tray. It adds no automatic startup entry and changes no execution policy. Enable tray completion alerts in **Settings → Studio care**; browser notifications are separate. Windows settings can suppress alerts. The controller's assemblies and paths were checked; visual tray and operating-system alert delivery remain unverified.

Storage review considers only export scratch folders from terminal export jobs older than 24 hours. A session-bound 15-minute review freezes the file listing; changed files, active jobs, links and escaping paths are rejected. Quarantine moves the reviewed folders into `backups/cleanup/` with a recoverable journal. Restore refuses to overwrite new files. Quarantine does **not** release physical drive space; no purge or automatic deletion is provided. Project media, model files, installed tools and arbitrary temporary folders are excluded.

## Backup and restore

Open a project, then **Settings → Back up selected project**. Bundles are saved under `backups/` and can be downloaded through authenticated, expiring links. They include metadata, revisions, job provenance and original media with hashes.

Restore creates a separate paused project with fresh project/scene/job/asset IDs. It verifies media and rejects unsafe paths or cross-project references. Credentials, executables and global workflow registrations are not imported. Failed restores are quarantined under `backups/failed-restore-*`.

Private directories include `projects/`, `database/`, `config/`, `models/`, `tools/`, `logs/`, `cache/`, `temp/`, `local/` and `backups/`. The agent binds only to loopback and uses exact origin/host checks, revocable sessions, one-use WebSocket tickets and asset-scoped expiring media links with Range support.

## Development

Use the isolated Python environment, `PYTHONPATH=backend` and a separate `STUDIO_ROOT`. Run `python -m pytest --rootdir=. --confcutdir=backend/tests -q`. FFmpeg/FFprobe are needed for media integration tests. Keep `TEMP` and `TMP` on the project drive.

Frontend: `npm ci`, `npm run dev`, `npm run build` under `frontend/`. GitHub Actions installs locked dependencies, tests, builds the relative-path frontend and deploys only its static output to Pages.
