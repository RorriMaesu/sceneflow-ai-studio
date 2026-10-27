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

## Phase 5 — Visual review and release

- The full local release suite passed 54 tests before the final selected-candidate and imported-media mapping checks were added. Production and quality tests were then rerun for those changes. CI runs the complete final suite before deployment.
- Real local vision inference reviewed a generated still and the first, middle and final frames of its matching video. Both jobs completed and the model unloaded. The model returned score 1.0 together with regeneration advice, including a video report with no issues. Added an explicit consistency guard: contradictory advice requires human review and cannot trigger regeneration. Raw advice remains visible.
- QA is off by default. Tests cover no inference while disabled, rejection of text-only models, human approval precedence, preservation of earlier media, a maximum of two retries, stopping without improvement, actionable low-score retry creation and conflicting high-score advice. Real automatic QA-driven regeneration was not performed; retry behavior was tested with controlled results.
- The complete eight-scene example finished with eight distinct real stills and eight distinct real animations. Actual file hashes, the exact still-to-video source links and all eight timeline source IDs were verified. FFprobe and full decoding verified the final silent H.264 movie: 1920×1080, 30 fps, 796 frames, 26.533333 seconds, 7,636,111 bytes, with a fade-through-black loop boundary. Native animation was 640×352 at 16 fps; export scales it to 1080p.
- These are automatic first takes. Visual inspection found character and style drift in several scenes. The complete movie proves the production pipeline; it still benefits from human selection and prompt refinement for consistent character likeness. The separate two-scene lantern movie provides another complete real planning-to-export proof.
- A real 11,616,968-byte backup of the complete eight-scene project was restored through the authenticated API into a separate eight-scene paused copy with fresh identifiers. The original project remained intact.
- Release checks cover revocation on existing WebSocket and media connections, host/origin validation, strict settings validation, uncertain-submission confirmation, owned FFmpeg recovery, source hash enforcement and unsupported imported-media rejection. Exact active cancellation is covered by ownership tests and inspection of the local backend's atomic per-job cancellation endpoint; a successful real render was not interrupted to demonstrate it.
- The setup uses pinned backend dependencies, an isolated environment, self-hosted fonts, split frontend bundles, a private diagnostics download, and start/stop scripts. The one-click launcher was exercised with browser opening disabled. Runtime data, media, pairing secrets, tools and model weights remain excluded from the public repository.

## Explicit verification boundaries

- The actual HTTPS Pages interface paired with the local agent and played local media in the available in-app Chromium browser. Standalone Edge/Chrome local-network permission grant, deny and revoke cases were unavailable to the test tools and remain unverified.
- LTX synchronized sound generation, specialized masking/outpainting/neural upscaling and first/last-frame conditioning require separately configured and verified adapters. They are presented as unavailable capabilities rather than successful generation.
- A small 20-scene scheduler simulation validates 40 dependent stages; it is not a benchmark of 40 real generations. Visual scores are advisory, and sampled frames cannot certify all motion or sound.

## Phase 6 — Creative continuity

- The installed native Qwen 2.1 editing template, node schemas and execution source established flattened reference-image inputs, the 64-channel latent format and mask semantics. The reference adapter reuses the existing INT8 model, encoder and VAE; no model download or ComfyUI package change was required.
- Four real 640×352, 20-step reference-guided stills completed from the same approved character image. Human inspection found the character recognizable across the four poses, with some costume/framing variation. Reference guidance improves control and does not establish guaranteed identity.
- The first real 25-step correction preserved all pixels outside its mask but changed interior composition too much. It was retained as an unselected take. The correction implementation was refined to encode the original latent, apply a denoising mask and retain the final pixel composite; the real acceptance run records the refined result separately.
- The refined 25-step, strength 0.6 correction completed. Human inspection found that the lantern structure was retained and the flame became blue; the surrounding amber light remained. Full-resolution comparison verified every zero-mask pixel unchanged. Both attempts and the original remain available; neither correction was automatically selected.
- The final local creative/quality/editing subset passed 22 checks. Image grids now use authenticated 320-pixel thumbnails while candidate inspection and correction use original-resolution assets.
- Phase 6 commit `6c78d8c` passed all 61 tests and Pages deployment in run `40439973940`. The completed four-shot proof is 1920×1080 H.264, 30 fps, 248 decoded frames, 8.266667 seconds, silent. All exact still/video/reference hashes and timeline order were checked. One real reference-aware still review completed with its actual reference and an advisory acceptance score of 1.0.

## Phase 7 — Editing and production control

- Added continuous draft playback with one playhead, cut snapping, source trim sliders, imported-audio waveforms and smaller frozen editing previews. Exact transitions and audio remain verified through FFmpeg rendering rather than promised by approximate browser playback.
- A separate Manual verification project imported two generated clips and a quiet synthetic effects tone. The exact rendered preview passed probe and full decode: 640×360 H.264, 24 fps, 100 frames, 4.166667 seconds, one 48 kHz stereo audio stream. A real protected waveform request returned 255 nonzero peak bins. The production stayed paused throughout explicit Director and preview work; no new image/video generation jobs were created.
- A real Director request initially proposed regeneration while asked only to change settings. It was left unapplied and dismissed. Added creative-only schemas by default, explicit operation-proposal opt-in and action/field consistency validation. A fresh real request then proposed only duration 1.5 and seed 773 for the selected scene; application verified the other scene body unchanged and retained the paused state.
- Added persisted reviewed commands with revision checks, elapsed budgets, per-stage video attempts, stop/continue/partial failure policies, no automatic failed-export retry loop, source-matched timing ranges, explicit-work pause isolation and stricter QA-advice consistency. Local checks passed 44 Director/production/editing tests, 22 foundation/quality tests and four final control checks before the last action-validation additions. CI runs the complete final suite before publication.
- LTX downloads were explicitly declined by the user. No LTX weights, external updater, ComfyUI package update or driver change was performed.
- Added tests for cross-project reference rejection, immutable reference IDs/hashes, rule invalidation, flattened graph inputs and source latents, changed-pixel rejection outside a mask, project-scoped export pagination beyond the global 100-asset bootstrap, zero retry limits, and reference remapping in restored bundles.
- Regression checks passed 42 foundation, production and quality tests before the final correction refinements. The complete deployment suite runs all final checks. New QA samples seven video times, includes frozen references and preserves the advisory/contradictory-result guard.
