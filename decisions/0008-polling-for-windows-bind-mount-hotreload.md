# 0008. File-watch polling for hot reload under Docker Desktop on Windows

## Context
Both dev containers hot-reload on source changes: `uvicorn --reload` restarts the Python API worker, and Vite serves updated frontend modules and pushes HMR updates. Docker Desktop's Windows bind mount doesn't reliably forward native filesystem change events (inotify) into the Linux container, so watchers that rely on those events see nothing. todo-app (Go) hit this with `air` and Vite, and the same applies here to uvicorn's watcher (`watchfiles`).

A separate issue from todo-app also still applies: the `web` service's `npm run dev -- --host 0.0.0.0` exited immediately (code 0, no output) when run detached in this container context, while `node node_modules/vite/bin/vite.js` directly kept running.

## Decision
- `docker-compose.yml` sets `WATCHFILES_FORCE_POLLING=true` on the `api` service, which makes `uvicorn --reload` (via `watchfiles`) poll `app/` instead of waiting for inotify events. `--reload-dir app` keeps it from watching `data/` and `tests/`.
- `web/vite.config.js` keeps `server.watch = { usePolling: true, interval: 500 }` (unchanged from todo-app).
- `web/Dockerfile.dev` and the `web` command invoke `node node_modules/vite/bin/vite.js --host 0.0.0.0 --clearScreen false` directly (unchanged from todo-app).

Verified live:
- Touching `api/app/routers/boards.py` while the stack was running produced `WatchFiles detected changes in 'app/routers/boards.py'. Reloading...`, followed by a fresh `Application startup complete`, and the API answered immediately afterwards.
- Touching `web/src/main.jsx` produced `[vite] page reload src/main.jsx`.

## Alternatives considered
- **Moving the repo into the WSL2 filesystem:** would likely fix inotify natively, but changes the project's location and workflow. The env var is a self-contained fix.
- **No hot reload (manual `docker compose restart api`):** works, but defeats the purpose of the dev stack.

## Consequences
- Polling costs a little CPU; on a project this size it's negligible.
- These settings are Windows-bind-mount workarounds. They're harmless, but unnecessary, on a native Linux Docker host.
- A uvicorn reload restarts the process. In-memory store state is rebuilt from the JSON files, which is safe because every write is persisted immediately (decisions/0004).
