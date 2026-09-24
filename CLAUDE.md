# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A full-stack todo app: a Python 3.12 **FastAPI** API (`api/`) with custom auth (HMAC-SHA256 tokens, PBKDF2-SHA512 password hashing via `hashlib`, account lockout, opt-in 2FA, Google OAuth) and JSON file storage, plus a React 18 + Vite 5 frontend (`web/`) with a drag-and-drop Kanban board and an admin panel. Everything runs via Docker Compose — there is no native Python/Node/npm/make installation on this machine, and none is required.

It is a port of the sibling project **todo-app** (`../todo-app`, Go backend). `web/` is copied from todo-app **unchanged**, and the Python API must keep the Go API's HTTP contract byte-compatible: same routes, status codes, `{"error":{"code","message"}}` bodies, JSON field names/order/omission, time format, redirects and cookies, and the same on-disk data and token formats (decisions/0014). When changing API behaviour, check the Go handler in `../todo-app/api/internal/handlers/` first, and keep the contract suite passing against both backends.

## Commands

Everything is a `docker compose` invocation; the `Makefile` targets are thin wrappers (`make` isn't installed here, so use the raw commands):

```
docker compose up                                   # full stack: api on :8080, web on :5173
docker compose up api                                # api only
docker compose build                                 # (re)build both images
docker compose down                                  # stop and remove containers
docker compose logs api                              # includes the admin bootstrap password on first run
.\start.ps1                                          # brings the dev stack up + tunnels web :5173 via ngrok
```

Production mode (nginx serves the prebuilt Vite bundle on :8081, uvicorn with one worker, no Node at runtime):
```
docker compose -f docker-compose.prod.yml up -d --build   # http://localhost:8081
docker compose -f docker-compose.prod.yml down
.\start.ps1 -Prod                                         # builds/ups prod + tunnels :8081
```

**Same host ports as todo-app (Go)**, so only one of the two apps can run at a time. `start.ps1` refuses to start if this app's other mode or either todo-app stack is running.

Tests (pytest, in the dev image):
```
docker compose run --rm api pytest                                  # everything except the contract suite
docker compose run --rm api pytest tests/test_labels.py -k delete   # a subset
docker compose run --rm --no-deps -e CONTRACT_BASE_URL=http://host.docker.internal:8080 api pytest tests/contract
```
The contract suite is black-box HTTP and registers random users, so only point it at an API running on throwaway data (e.g. a Compose override that mounts a temp dir at `/app/data`), never `api/data`.

Frontend build/install:
```
docker compose run --rm web npm install
docker compose run --rm web npm run build
```

No linter/formatter is configured.

## Git workflow

Never commit directly to `main`. For any change: create a branch, make and verify the change there, push the branch, and open a PR (`gh pr create`). Don't push straight to `main` and don't merge the PR automatically.

## Architecture

### Docker layer
Dev (`docker-compose.yml`, project `todo-app-py`): `api` is `python:3.12-slim` running `uvicorn app.main:app --reload --reload-dir app` over a bind-mounted `./api`, with `WATCHFILES_FORCE_POLLING=true` because Docker Desktop's Windows bind mount doesn't propagate file-change events (decisions/0008). `web` is identical to todo-app: `node:20` running Vite directly via `node node_modules/vite/bin/vite.js`, **not** `npm run dev` (that wrapper exits immediately in this container context), with `usePolling` in `vite.config.js`. The browser only talks to `localhost:5173`; Vite proxies `/api/*` to `http://api:8080` (Docker service-name DNS). `api/data` is bind-mounted so JSON storage, the HMAC secret and attachment blobs persist.

Prod (`docker-compose.prod.yml`, project `todo-app-py-prod`): `web/Dockerfile` runs `vite build` in a throwaway Node stage and ships only `dist/` in `nginx:alpine`; `web/nginx.conf` proxies `/api/` to `http://api:8080`, falls back `/admin` → `index.html`, gzips, caches hashed assets forever, and sets `client_max_body_size 11m` for the 10MB attachment cap. `api/Dockerfile` installs deps into `/venv` in a builder stage; the runtime image has only the venv + `app/` and runs uvicorn with `--workers 1 --proxy-headers`. The api isn't published on the host in prod. Prod shares `api/data` with dev. Prod Google URLs come from `PROD_GOOGLE_REDIRECT_URI` / `PROD_FRONTEND_BASE_URL`.

### Backend (`api/app`)
- `main.py` — `create_app(config)`: loads the stores + secret (`state.py`), bootstraps `admin@todo.io` on an empty user store, installs error handlers, includes one router per resource, adds Go-style request logging. FastAPI docs/OpenAPI routes and trailing-slash redirects are disabled. A module-level `app` is built at import unless `TODO_APP_NO_AUTOCREATE` is set (tests set it).
- **Must run with exactly one worker**: `storage.py`'s `Store` keeps the whole collection in memory behind a `threading.Lock` and rewrites the JSON file atomically (temp file → fsync → `os.replace`) on every put/delete. Entities are **deep-copied** in and out (Go value semantics), so mutating a fetched entity changes nothing until `put()`.
- `models.py` / `jsonfmt.py` — dataclasses with hand-written `to_dict`/`from_dict` reproducing Go's `encoding/json` output: field order, `omitempty` (e.g. task `due_date`/`label_ids` omitted when empty), zero time emitted as `"0001-01-01T00:00:00Z"`, RFC3339Nano times, `[]byte` as base64 (nil → `null`). `User.public()` is the only user shape sent to clients.
- `body.py` — strict request decoding equivalent to Go's `DisallowUnknownFields`: unknown field / wrong JSON type / empty or invalid body → 400 `invalid_body`; null leaves plain fields at their zero value and "pointer" fields (`OPT_STR`, `OPT_STR_LIST`) as `None` = "not provided" (task PUT is a partial update). Handlers never use Pydantic body models for this reason.
- `errors.py` — `ApiError(status, code, message)` → `{"error":{...}}`; unmatched routes/methods return Go ServeMux's plain-text `404 page not found` / `Method Not Allowed`; unhandled exceptions → 500 `internal_error`. Use `json_response()` (compact JSON, `application/json` with no charset), never FastAPI's default response serialization.
- `security.py` — `require_user` (Bearer token → `tokens.verify` → load user, else 401) and `require_admin` (403) dependencies.
- `auth/` — `passwords.py` (`hashlib.pbkdf2_hmac` SHA-512, 100k iterations, 64-byte key, 16-byte salt), `tokens.py` (`base64url(json{"uid","adm","exp"}).hex(hmac_sha256)`, 24h, not JWT, stateless — logout is client-side), `secret.py` (32-byte `data/secret.key`), `twofactor.py`, `google.py` (httpx token exchange + userinfo).
- `routers/` — one module per resource, mirroring the Go handlers. Sync `def` handlers (FastAPI runs them in a threadpool) read the raw body via the `raw_body` dependency and decode it with `body.decode`. Ownership failures return **404** (never confirm existence to non-owners); admin routes return 403. Login always runs PBKDF2 (dummy hash for unknown/Google-only accounts) before any early return; 3 failed logins lock the account for 30 minutes. Deletes cascade: board → tasks → attachments (+ blobs) and the board's labels; task → attachments; label → stripped from tasks' `label_ids`.
- Log lines that the README tells users to grep for (admin bootstrap block, `password reset requested for … reset_token=…`, `two-factor code requested for … code=…`) must keep their exact wording.

### Frontend (`web/src`)
Unchanged from todo-app. No React Router — `main.jsx` picks `App.jsx` or `admin/AdminApp.jsx` from `window.location.pathname`; `api.js` is the single fetch wrapper (bearer token from `localStorage`, 401 → back to login); inline styles from `theme.js`; native HTML5 drag-and-drop; `AttachmentUploader.jsx` fetches attachments as authenticated blobs.

## Documentation

- [`decisions/`](decisions/README.md) — ADRs. 0001–0013 come from todo-app (language-specific details translated); 0002, 0005 and 0008 were rewritten for Python; 0014 records the port itself.
- [`diagrams/`](diagrams/README.md) — Mermaid architecture / auth sequence / data model / dev-vs-prod serving diagrams.
- [`features/`](features/README.md) — per-feature reference (routes, key files, UI flow).
