# Todo App (Python API)

Full-stack todo app: a **Python 3.12 / FastAPI** API with custom auth (HMAC
tokens, PBKDF2-SHA512 password hashing, account lockout, opt-in 2FA, Sign in
with Google) and JSON file storage, plus a React 18 + Vite 5 frontend with a
drag-and-drop Kanban board, labels, due dates, attachments and an admin panel.

This is a port of [todo-app](https://github.com/kasamajay/todo-app), which has
a Go backend. **The React frontend is copied unchanged.** The Python API
exposes exactly the same HTTP contract (routes, status codes, error bodies,
JSON shapes) and uses the same on-disk data and token formats, so a data
directory can be moved between the two backends. See
[`decisions/0014`](decisions/0014-python-fastapi-port.md).

Everything runs via **Docker Desktop** - no native Python, Node, npm, or make
installation is required or used.

## Quick start

```
docker compose up
```

- API: http://localhost:8080
- Web app: http://localhost:5173
- Admin panel: http://localhost:5173/admin

On first boot the API creates an `admin@todo.io` account with a random
password and **prints it once** to the API container logs:

```
docker compose logs api
```

Look for a block like:

```
Bootstrapped admin account (shown only once):
  email:    admin@todo.io
  password: <random>
```

Save it - it is never shown again (though you can always reset it via
"Forgot password?" on the admin login, since the reset token is logged
server-side - see below).

**Same ports as todo-app (Go).** Both apps use 5173 / 8080 / 8081, so only one
of them can run at a time - `docker compose down` in the other project first.

## Dev mode

- `web`: Vite's dev server compiles each `.jsx` on demand and pushes changes
  to the browser over an HMR WebSocket; it proxies `/api/*` to the `api`
  container.
- `api`: `uvicorn app.main:app --reload` - saving a file under `api/app/`
  restarts the worker (watchfiles, in polling mode because Docker Desktop's
  Windows bind mount doesn't forward file-change events;
  [`decisions/0008`](decisions/0008-polling-for-windows-bind-mount-hotreload.md)).

## Production mode

Production mode compiles and bundles the frontend at image build time and
serves it as static files from **nginx** - no Node process runs at all:

```
docker compose -f docker-compose.prod.yml up -d --build
```

- Web app: http://localhost:8081
- Admin panel: http://localhost:8081/admin
- Stop: `docker compose -f docker-compose.prod.yml down`

```
browser -> nginx :8081 --+-- /assets/*, index.html  (prebuilt Vite bundle)
                         +-- /api/*  -> api :8080   (uvicorn, 1 worker, not exposed on the host)
```

- `web/Dockerfile` runs `vite build` in a throwaway `node:20` stage and copies
  only `dist/` into `nginx:alpine`; `web/nginx.conf` does the `/api` proxy,
  the `/admin` -> `index.html` fallback, gzip, and caching (hashed
  `/assets/*` cached forever, `index.html` always revalidated).
- `api/Dockerfile` installs the dependencies into a virtualenv in a builder
  stage; the runtime `python:3.12-slim` image gets only that venv and `app/` -
  no tests, dev dependencies or build tools. uvicorn runs **one worker**, since
  the JSON stores keep in-memory state and assume a single writer process.
- It runs under its own Compose project (`todo-app-py-prod`) but **shares
  `api/data`** with dev - same users and tasks. Don't run both stacks at once.
- Google sign-in in prod: add `http://localhost:8081/api/auth/google/callback`
  as an extra Authorized redirect URI in Google Cloud Console. Override the
  prod URLs with `PROD_GOOGLE_REDIRECT_URI` / `PROD_FRONTEND_BASE_URL` in `.env`.
- Code changes need a rebuild (`--build`) - there is no hot reload.

See [`decisions/0013`](decisions/0013-production-mode-nginx-static-bundle.md), and
[`diagrams/dev-vs-prod-serving.md`](diagrams/dev-vs-prod-serving.md) for a
walkthrough of how each mode serves the frontend.

## Public access via ngrok

To reach the app from another device, or share it with someone, expose it via [ngrok](https://ngrok.com) (requires `ngrok` installed and authenticated: `ngrok config add-authtoken <token>`):

```
.\start.ps1          # dev mode, tunnels :5173
.\start.ps1 -Prod    # production mode, rebuilds and tunnels :8081
```

The script brings the stack up if needed, tunnels the `web` container's port, and prints a public HTTPS URL. Only that one port needs tunneling - Vite (dev) or nginx (prod) proxies `/api/*` to the `api` container, so the same URL serves the whole app, including `<url>/admin`. Ctrl+C stops the tunnel only; the Docker stack keeps running.

It refuses to start when a conflicting stack is running - this app's other mode (they share `api/data`) or either todo-app (Go) stack (same ports) - and prints the `down` command to run first. See [`decisions/0009`](decisions/0009-ngrok-for-public-exposure.md).

## Sign in with Google (optional)

The login screen has a "Sign in with Google" button. It's disabled by default
(clicking it returns an error) until you configure your own OAuth client:

1. https://console.cloud.google.com/apis/credentials → select or create a project.
2. **OAuth consent screen** → User type "External", fill in the required
   fields, leave it in **Testing** mode (add your own Google account as a
   test user if prompted).
3. **Credentials → Create Credentials → OAuth client ID** → Application type
   **Web application**.
4. **Authorized redirect URIs** → add exactly
   `http://localhost:5173/api/auth/google/callback`.
5. Copy the generated **Client ID** and **Client secret**.
6. `cp .env.example .env`, then fill in `GOOGLE_CLIENT_ID=` and
   `GOOGLE_CLIENT_SECRET=` with those values.
7. `docker compose up -d api` (recreate, so Compose re-reads `.env`).

If you already set this up for todo-app (Go), the same OAuth client and
redirect URIs work here - the ports and callback paths are identical, so you
can copy that project's `.env`.

### Google sign-in over ngrok

ngrok's free tier normally hands out a new random URL every run, which can't
be pre-registered with Google. Fix this once with a free static ngrok domain:

1. https://dashboard.ngrok.com/domains → **+ Create Domain**.
2. Add `NGROK_DOMAIN=<name>.ngrok-free.app` to `.env`.
3. In Google Cloud Console, add `https://<name>.ngrok-free.app/api/auth/google/callback`
   as an Authorized redirect URI.
4. In `.env`, set `GOOGLE_REDIRECT_URI=https://<name>.ngrok-free.app/api/auth/google/callback`
   and `FRONTEND_BASE_URL=https://<name>.ngrok-free.app` (for `-Prod`, the
   `PROD_`-prefixed versions of both).
5. `docker compose up -d api`, then `.\start.ps1`. See
   [`decisions/0012`](decisions/0012-optional-ngrok-static-domain-for-google-oauth.md).

## Tests

```
docker compose run --rm api pytest                 # unit + handler + parity tests
docker compose run --rm api pytest tests/test_tasks.py -k due_date   # a subset
```

- The 50 tests of the Go API are ported one-to-one (PBKDF2 vectors, tokens,
  Google OAuth, 2FA, labels, tasks, board cascades), plus parity tests for the
  Go-specific wire details the frontend relies on (time format, omitted
  fields, strict body decoding, error envelopes, 404/405, 413, cookies) and
  reading Go-written data files.
- **Contract suite** (`api/tests/contract/`): black-box HTTP tests that run
  against *any* backend. Point it at a running API on throwaway data:

  ```
  docker compose run --rm --no-deps -e CONTRACT_BASE_URL=http://host.docker.internal:8080 api pytest tests/contract
  ```

  The same suite passes against both this API and todo-app's Go API.

## Makefile / raw docker compose commands

A `Makefile` is provided, but `make` isn't required - every target is a thin
wrapper you can run directly:

| Make target      | Equivalent command                              |
|------------------|---------------------------------------------------|
| `install-tools`  | `docker compose build`                             |
| `dev-api`        | `docker compose up api`                             |
| `dev-web`        | `docker compose up web`                             |
| `dev`            | `docker compose up`                                 |
| `test`           | `docker compose run --rm api pytest`               |
| `build`          | `docker compose build`                              |
| `down`           | `docker compose down`                               |
| `prod-build`     | `docker compose -f docker-compose.prod.yml build`   |
| `prod-up`        | `docker compose -f docker-compose.prod.yml up -d --build` |
| `prod-down`      | `docker compose -f docker-compose.prod.yml down`    |

## Project layout

```
api/          Python 3.12 FastAPI app (api/app), pytest suite (api/tests), JSON file storage in api/data/
web/          React 18 + Vite 5 frontend (identical to todo-app), inline styles only, brand color #6366f1
decisions/    ADRs - why things are built the way they are
diagrams/     Mermaid diagrams of the architecture, auth flow, data model, dev vs prod serving
features/     What each feature does - API routes, key files, UI flow
```

## Documentation

- [`decisions/`](decisions/README.md) - architecture decision records: why Docker-only dev, why custom HMAC tokens, why cascading deletes, why FastAPI with strict Go-contract parity, etc.
- [`diagrams/`](diagrams/README.md) - system architecture, auth request sequence, and data model diagrams, plus [dev vs production serving](diagrams/dev-vs-prod-serving.md): on-demand JSX compilation and the HMR WebSocket vs the nginx static bundle and `/api` proxy.
- [`features/`](features/README.md) - what each feature area does: authentication, boards, tasks/kanban, labels, attachments, admin panel.

## API

| Method | Path | Auth |
|---|---|---|
| POST | `/api/auth/register` | none |
| POST | `/api/auth/login` | none |
| POST | `/api/auth/logout` | bearer |
| GET | `/api/auth/me` | bearer |
| POST | `/api/auth/forgot-password` | none |
| POST | `/api/auth/reset-password` | none |
| POST | `/api/auth/2fa/verify` | none (pending challenge) |
| PUT | `/api/auth/2fa` | bearer |
| GET | `/api/auth/google/login` | none |
| GET | `/api/auth/google/callback` | none |
| GET/POST | `/api/boards` | bearer |
| PUT/DELETE | `/api/boards/{id}` | bearer (owner) |
| GET/POST | `/api/tasks` | bearer |
| PUT/DELETE | `/api/tasks/{id}` | bearer (owner) |
| GET/POST | `/api/labels` | bearer |
| PUT/DELETE | `/api/labels/{id}` | bearer (owner) |
| POST/GET | `/api/tasks/{id}/attachments` | bearer (owner) |
| GET/DELETE | `/api/tasks/{id}/attachments/{aid}` | bearer (owner) |
| GET | `/api/admin/users` | bearer + admin |
| POST | `/api/admin/users/{id}/unlock` | bearer + admin |
