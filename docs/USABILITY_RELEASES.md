# Usability releases

## Phase 9 — Clear status and protected drafts

Timeline, project and look drafts persist separately from saved production revisions. Conflicting server revisions block overwrite; browser storage failures are surfaced. A draft remains local to its browser/origin and does not start generation. Rebuilding a cut is disabled while a draft is pending.

The live browser regression reproduced an unsaved trim of 0.0625 seconds, navigated away and back, then reloaded. The trim and Save action remained available in both cases. The temporary test draft was discarded afterward without changing the saved cut.

Added six dependency-free frontend checks for recoverable drafts, malformed/failed storage, unknown production state, explicit work while paused, and project isolation. The deployment now runs frontend checks as well as the existing 81 backend checks and production build.

The project header now displays actual work status and a labeled Pause/Resume control. New-video actions create a new project flow, navigation resets scroll/focus, mode selections expose their state, and core typography/contrast are larger and clearer.

Phase 9 commit `bad3482` passed deployment run `40532006451`.

## Phase 10 — Guided creation

Global navigation is My videos, Activity, Help and Settings. Projects have five task-based steps: Story, Look & photos, Motion, Edit and Save video. Advanced tools remain available on demand. Activity has explicit all-video/project filtering and matches its global badge scope.

The new-video form accepts an idea, approximate length, shape, work mode and optional local reference. Installed planning tools are recommended automatically; planning remains reviewable and does not begin diffusion generation. A live Manual setup created a separate test project, with zero generation jobs. Existing proof footage was imported afterward for interface acceptance checks.

Guided stage requests identify exact missing scene IDs, preflight all requested work, reject foreign IDs, preserve the paused state and never force regeneration of valid completed work. Twenty-seven local production checks passed, including the new scope/pause regression. Eight frontend checks and the production build passed.

Phase 10 commit `bf7078b` passed deployment run `40534412032`.

## Phase 11 — Clear scene review

Scene review now has a larger current preview beside its editing controls, a compact scene list, named photo/clip versions and one Use this photo/clip action. Optional AI checks and precise timeline controls are progressively disclosed. Scene tabs support keyboard selection and expose their selected state.

Director requests show their target scene/video. Proposals show named scenes and readable current/proposed values, distinguish requested operations, and block outdated proposals. The Look section consolidates style, consistency guidance and owned references without discarding existing values.

Existing scene drafts migrate into the shared recoverable-draft format. Live browser testing retained a temporary scene title across navigation and restored the saved title through Discard. The Director opened with the exact selected scene as its visible target. Eleven frontend checks and the production build passed. Manual control has its own truthful status without a misleading global Resume button.

Phase 11 commit `f49362f` passed deployment run `40536053461`.

## Phase 12 — Easy finishing and recovery

Save video distinguishes an unapplied draft, an empty edit, work in progress, previews, earlier versions and the current saved result. It offers a protected MP4 download and Show in folder for owned Windows exports. Asset-scoped download tickets are separate from playback tickets and stop working when their session is revoked. Native folder selection is tested with a mocked process launcher; visual Explorer behavior remains unverified.

Settings now separates notifications, connection help and advanced troubleshooting/maintenance. Activity names the video and task in plain language, offers explicit scope/history filters, and preserves careful recovery of uncertain submissions. Errors remain visible until dismissed. Advanced actions and all three production modes remain available.

Live acceptance created a Manual project through the new form, imported existing proof media, built a two-clip edit, protected its drafts across navigation/reload, blocked an unapplied draft from export, and saved after rapid navigation. Its actual browser download matched the registered output hash and passed full decode: 1920×1080 H.264, 30 fps, 120 frames, 4.0 seconds, silent. This is an editing/download proof using existing footage, not a claim of new diffusion generation.

The corrected guided AI setup also created a tall-video project with 1080×1920 export settings and ran the installed local Director. One real planning job completed with four proposed scenes, still unapplied for review; no photo/video generation job was started. Shape initialization no longer tries to save an empty edit.

Final acceptance caught stale cached revisions and saves completing after a screen unmounts. Applied drafts are now cleared synchronously, same-window draft changes refresh finishing controls, and server-only timeline bookkeeping does not create false creative conflicts. A newer genuinely different saved version still blocks overwrite. Tests cover all three output shapes and these draft cases.

Final frontend checks: 14 passed; local production checks: 27 passed; local foundation/security checks: 20 passed. The complete deployment gate runs the final 87 backend tests and all 14 frontend tests plus the production build. This is expert/browser acceptance, not a novice-user study or full accessibility certification. Standalone Edge/Chrome permission cases, screen readers and native tray delivery remain unverified.
