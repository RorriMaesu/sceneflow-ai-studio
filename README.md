# SceneFlow AI Studio

A local AI filmmaking studio: plan scenes, create starting stills, animate their exact images, review takes, and assemble a movie. The public interface is hosted on GitHub Pages; all private data and computation remain in a loopback Windows agent.

**Current release: Phase 2 — Image-first production.** Project/scene persistence, safe revisions, secure pairing, real local model discovery, Qwen still generation, Wan animation from the exact selected still, durable background jobs, candidate review, a basic timeline and verified silent MP4 exports are implemented. AI Director, richer editing and optional vision QA arrive in subsequent phases and remain unavailable until enabled and verified.

See the [verification ledger](docs/EVIDENCE.md) for actual tests and known limits. A real still → video → validated 1080p preview export has completed through the UI. This does not yet establish completion of all planned production features.

See [the optimized build plan](docs/BUILD_PLAN.md) for architecture, invariants, phases and acceptance criteria.

## Install locally

1. Keep this checkout at `M:\AI-Video-Studio` (or another drive with adequate space).
2. Install Python 3.11 and Node.js 22+ if not already available. The app never changes ComfyUI's Python.
3. Run `SETUP_STUDIO.bat`, then `START_STUDIO.bat`.
4. Open `http://127.0.0.1:8770` or the published Pages interface. Enter the pairing code printed by the launcher.

The agent binds only to `127.0.0.1:8770`. The launcher must remain running; the browser may close. A modern browser may ask permission to access the local agent. The same-origin local interface is the fallback if Pages connectivity is blocked.

Data lives under `projects/`, `database/`, `config/`, `logs/`, `cache/`, `temp/` and `backups/`, all excluded from Git. Do not copy these directories into a public repository. Model files remain in the existing ComfyUI installation.

## Development

Backend: `PYTHONPATH=backend python -m pytest backend/tests -q`.

Frontend: `cd frontend`, `npm ci`, `npm run dev` or `npm run build`.

The Pages workflow tests the backend, builds the frontend using relative asset paths, and deploys the static artifact. It never publishes local media or secrets.
