---
name: docker-dev-workflow
description: >
  Building, running, and testing todo-app-py entirely through Docker Compose -
  no native Python/Node/npm/make - plus exposing it publicly via ngrok
  (start.ps1), including the real bugs hit setting this up (npm run dev
  exiting immediately in this container context, Windows bind-mount
  file-watching for both uvicorn and Vite, Vite blocking ngrok's Host header,
  and the shared ports with todo-app). Use when `docker compose up` fails, hot
  reload isn't picking up changes, ngrok exposure isn't working, or you're
  about to change a Dockerfile, docker-compose*.yml, or vite.config.js.
---

# Docker dev workflow (todo-app-py)

## Table of Contents

- [Overview](#overview)
- [When to Use](#when-to-use)
- [Quick Start](#quick-start)
- [Known issues (hit for real)](#known-issues-hit-for-real)
- [Best Practices](#best-practices)

## Overview

Everything runs via Docker Compose. There's no native Python, Node or `make` on this machine, and none is needed. There are two containers:
- `api`: `python:3.12-slim` running `uvicorn --reload`.
- `web`: `node:20` running Vite's dev server.

They're joined on Docker's default bridge network. See `../../../decisions/0001-docker-only-dev-workflow.md`.

This project uses **the same host ports as the sibling `todo-app` (Go)**: 5173, 8080 and 8081. Only one of the two apps can be up at a time.

## When to Use

- Starting or stopping the stack, running tests, or rebuilding images.
- `docker compose up` fails with "port is already allocated". That's usually todo-app (Go) still running.
- Editing a file under `api/app/**` or `web/src/**` doesn't take effect without a manual restart.
- Touching `api/Dockerfile*`, `web/Dockerfile*`, `docker-compose*.yml`, or `web/vite.config.js`.

## Quick Start

```
docker compose up                    # full stack: api :8080, web :5173
docker compose build                 # rebuild both images
docker compose run --rm api pytest   # unit + handler + parity tests
docker compose run --rm web npm install
docker compose logs api              # admin bootstrap password is printed here on first run
docker compose down
```

`make` isn't installed. The `Makefile` targets wrap exactly the commands above.

### Exposing via ngrok

```
.\start.ps1          # dev: brings the stack up if needed, tunnels web :5173
.\start.ps1 -Prod    # production: nginx :8081, rebuilt with --build
```

Only the `web` container needs tunneling, because Vite (dev) or nginx (prod) proxies `/api/*` to `api`. The script refuses to start when this app's other mode, or either todo-app (Go) stack, is running. It checks Docker's `com.docker.compose.project` labels: `todo-app-py`, `todo-app-py-prod`, `todo-app`, `todo-app-prod`.

## Known issues (hit for real)

1. **`npm run dev -- --host 0.0.0.0` exits immediately with code 0 and no output** in this container context (found in todo-app). `npx vite` fails the same way. **Fix applied:** `web/Dockerfile.dev` and the `web` command run `node node_modules/vite/bin/vite.js --host 0.0.0.0 --clearScreen false` directly. Don't "simplify" this back.

2. **Hot reload doesn't fire on host-side edits.** Docker Desktop's Windows bind mount doesn't forward inotify events into the container. **Fixes applied:**
   - `docker-compose.yml` sets `WATCHFILES_FORCE_POLLING=true` for `uvicorn --reload --reload-dir app`.
   - `web/vite.config.js` has `server.watch.usePolling`.

   To verify, touch a file under `api/app/` and `docker compose logs api` should show `WatchFiles detected changes in '...'. Reloading...` followed by `Application startup complete`. See `../../../decisions/0008-polling-for-windows-bind-mount-hotreload.md`.

3. **A request through the ngrok tunnel gets Vite's `Blocked request. This host is not allowed`.** **Fix applied:** `web/vite.config.js`'s `server.allowedHosts` lists ngrok's domain suffixes. In production, nginx (`server_name _`) accepts any Host.

4. **Tests or the dev server write into `api/data`.** Importing `app.main` builds the app against `DATA_DIR`, which defaults to `./data`. `tests/conftest.py` sets `TODO_APP_NO_AUTOCREATE=1` before importing, and each test uses its own tmp dir. Keep it that way. The contract suite (`tests/contract`) registers real users, so only run it against an API whose `/app/data` is a throwaway mount.

## Best Practices

### ✅ DO
- After changing `docker-compose*.yml`, a Dockerfile or `vite.config.js`, prove hot reload still works: touch a source file and check the logs. Don't just check that the containers are "Up".
- Reset data for a fresh admin bootstrap: `docker compose down`, delete everything in `api/data/` except `.gitkeep`, then `docker compose up -d`.
- Use `MSYS_NO_PATHCONV=1` when passing Unix-style paths to `docker` from Git Bash.
- Run the API with exactly one uvicorn worker, in dev and prod (see the `python-contract-parity-api` skill).

### ❌ DON'T
- Don't revert the `web` command to `npm run dev`.
- Don't start this app while todo-app (Go) is up. The ports collide, and `start.ps1` will refuse anyway.
- Don't assume a missing reload log line means the edit didn't save. Check the polling config first.
