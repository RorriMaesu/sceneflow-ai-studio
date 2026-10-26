# Troubleshooting and recovery

## Connection

Open START_STUDIO.bat. A second launcher reuses the owned agent. An older owned version can be restarted while ComfyUI retains its render. Another service occupying the port causes a clear startup failure.

Allow local-network access when a supported browser asks. If Pages connectivity is blocked, use http://127.0.0.1:8770. Browser protections can remain enabled.

Create a fresh code if one expired or was consumed. Revoking a browser invalidates its media links and closes its event socket.

## Waiting jobs

Read the queue explanation: review, pause, outside ComfyUI work, loaded Ollama sessions, memory headroom or drive space. External work is observed without interruption.

Refresh Model Library after model/node changes. Ready establishes required files, nodes and mappings. Generation verified additionally records a successful output and its measured preset.

Pending edits affect only related jobs. Active edits create revisions while the running attempt keeps its original inputs. Previous takes remain in the inspector; selecting a video restores its associated starting still.

## Uncertain submissions

The agent reconciles the original prompt ID and Studio job metadata against ComfyUI queue/history before retrying. When neither establishes what happened, the job needs attention. Inspect backend evidence before explicitly retrying.

Cancellation uses the verified backend's atomic per-job endpoint after checking Studio ownership. It never falls back to global interrupt. Earlier takes remain available. A result finishing during cancellation is preserved as an unselected take.

## Export

Run Settings → Readiness check. Add portable FFmpeg/FFprobe under tools/ffmpeg if missing. Exports verify source hashes, paths, trims, dimensions, duration and audio policy. Changed source bytes require restoration or a new import.

Save the timeline before exporting. Earlier exports retain frozen versions. Partial previews are labeled. User-edited cuts are preserved when automatic production finishes; build from selected takes to replace one deliberately.

After restart, a recorded owned export worker is verified and stopped before retrying the frozen export. Unconfirmed ownership requires attention. Re-executing a completed attempt reuses its asset.

## Vision advice

Inspect the actual media. Model scores and confidence are advisory. Testing found perfect scores paired with regeneration advice, including a result with no issues. Contradictory advice is flagged for human review. Approve the exact asset to override automated recommendations.

Disable AI QA to continue with technical checks. A vision model is optional; large models are never installed automatically.

## Storage

Keep runtime storage and temporary files on the project drive. Model loading and synchronous test writes can contend for the same drive; testing slowed while the full film was generating.

Back up before filesystem maintenance. Restore creates a separate paused copy. Retain failed-restore quarantine folders until inspected. Older takes and model weights are not deleted automatically.

Private logs live in logs/. Downloadable diagnostics exclude prompts, conversations, pairing codes, session tokens and raw logs. Ticket values are redacted from application logging.
