# Usability releases

## Phase 9 — Clear status and protected drafts

Timeline, project and look drafts persist separately from saved production revisions. Conflicting server revisions block overwrite; browser storage failures are surfaced. A draft remains local to its browser/origin and does not start generation. Rebuilding a cut is disabled while a draft is pending.

The live browser regression reproduced an unsaved trim of 0.0625 seconds, navigated away and back, then reloaded. The trim and Save action remained available in both cases. The temporary test draft was discarded afterward without changing the saved cut.

Added six dependency-free frontend checks for recoverable drafts, malformed/failed storage, unknown production state, explicit work while paused, and project isolation. The deployment now runs frontend checks as well as the existing 81 backend checks and production build.

The project header now displays actual work status and a labeled Pause/Resume control. New-video actions create a new project flow, navigation resets scroll/focus, mode selections expose their state, and core typography/contrast are larger and clearer.
