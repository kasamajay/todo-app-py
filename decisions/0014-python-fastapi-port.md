# 0014. Python (FastAPI) port of the API with strict contract and data parity

## Context
todo-app has a React/Vite frontend and a stdlib-only Go API. The goal of todo-app-py is the **same application with the API written in Python**: every feature (password auth with lockout, password reset, opt-in 2FA, Sign in with Google, boards, tasks with due dates and labels, attachments, admin panel), plus the same dev mode (Vite HMR + API hot reload) and production mode (nginx serving a prebuilt bundle and proxying `/api`).

## Decision
**Framework: FastAPI on uvicorn.**
- FastAPI is the idiomatic modern choice.
- `uvicorn --reload` gives dev-mode hot reload (the counterpart of `air`), and uvicorn serves in production behind nginx.
- Dependencies are pinned in `api/requirements.txt`: fastapi, uvicorn[standard], python-multipart and httpx. pytest is dev-only.

**The React frontend is copied from todo-app unchanged**, and the Python API reproduces the Go API's HTTP contract exactly. Keeping the frontend untouched is what proves feature parity:
- The same routes, status codes and `{"error":{"code","message"}}` bodies (every code and message string is identical).
- The same JSON shapes, as Go's `encoding/json` produces them: field order, `omitempty` behaviour, RFC3339Nano times with the zero time `0001-01-01T00:00:00Z` still emitted, and `[]byte` as base64 with nil as `null`. See `app/models.py` and `app/jsonfmt.py`.
- Request decoding as strict as Go's `DisallowUnknownFields` (`app/body.py`).
- Go ServeMux's plain-text 404/405 (decisions/0005), 302 redirects and cookie attributes for Google OAuth, the 10MB attachment limit with 413, and `Content-Disposition` on downloads.
- Log lines with the same wording (admin bootstrap, logged reset tokens and 2FA codes; decisions/0007 and 0011).

**Data and token compatibility:** the same JSON file layout, PBKDF2 parameters (decisions/0002), token format and `secret.key` (decisions/0003). A data directory can move between the two backends, and a token minted by one verifies in the other.

**One uvicorn worker.** Like the Go binary, the store keeps each collection in memory and assumes a single writer process (decisions/0004). Concurrency comes from FastAPI's threadpool, since handlers are sync `def` functions, with a lock per store. Entities are deep-copied in and out of the store, matching Go's value semantics, so a rejected request never leaves a half-applied mutation in memory.

**Same host ports as todo-app** (5173 / 8080 / 8081). The existing Google OAuth redirect URIs and `.env` work unchanged, at the cost that only one of the two apps can run at a time. `start.ps1` enforces this.

## Verification
- The 50 Go unit and handler tests are ported one-to-one to pytest, plus parity tests for the wire details above. There are 96 tests in total.
- `tests/contract/` is a black-box HTTP suite. It passes unchanged against **both** the Go API and the Python API.
- Data compatibility was checked in both directions:
  - The Go API loaded a Python-written data directory and accepted its password hashes.
  - The Python API accepted a Go-minted token.
  - Every record of a copy of real Go dev data round-trips through the Python models unchanged, apart from nanosecond → microsecond time precision.

## Alternatives considered
- **Stdlib only (`http.server`)**, mirroring the Go project's no-dependencies rule: routing, multipart parsing (the `cgi` module is gone in Python 3.13) and a dev reloader would all be hand-written, a lot of code with no user-visible benefit.
- **Flask + gunicorn:** perfectly viable. FastAPI was preferred for its dependency injection (auth/admin/state wiring) and first-class uvicorn reload.
- **Letting FastAPI's defaults define the contract** (Pydantic models, 422 errors, JSON 404s): less code, but the unchanged frontend and a shared data directory would no longer be guaranteed to work.

## Consequences
- Behaviour changes must be made in **both** projects (or deliberately diverge), and the contract suite is the tool for checking that they agree.
- Python's datetime has microsecond precision, so times written by the Python API have at most 6 fractional digits (Go writes up to 9). Both parse either form.
- The production API image is ~170MB (python:3.12-slim + venv) versus ~15MB for the static Go binary.
