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
