# 0005. FastAPI routing, with the Go ServeMux behaviour reproduced at the edges

*Replaces todo-app's 0005 ("Go 1.22 stdlib `http.ServeMux` routing, no router package").*

## Context
The API needs method-aware routes with path parameters (`PUT /api/boards/{id}`, `GET /api/tasks/{id}/attachments/{aid}`). The Go backend uses Go 1.22's `http.ServeMux` patterns. In Python the web framework does the routing (FastAPI was chosen in decisions/0014), but its defaults differ from ServeMux in ways a client can observe.

## Decision
- One `APIRouter` per resource in `api/app/routers/`, with the same method + path table as the Go `main.go`. Path parameters are plain function arguments (`def update_board(id: str, ...)`).
- The defaults that would change the contract are turned off or overridden in `main.py` / `errors.py`:
  - `redirect_slashes=False`: `/api/boards/` is a 404, as in Go, instead of a 307 redirect.
  - `docs_url`, `redoc_url` and `openapi_url` are `None`, so there are no extra routes.
  - Unmatched paths return Go's plain-text `404 page not found`, and wrong methods return `Method Not Allowed` (405), instead of FastAPI's `{"detail": ...}` JSON.
  - `RequestValidationError` (FastAPI's 422) never reaches clients. Handlers don't declare Pydantic body models; they decode the raw body with `body.decode` (strict, Go-equivalent), and any stray validation error maps to 400 `invalid_body`.
- Auth is expressed as dependencies (`Depends(require_user)` / `Depends(require_admin)`) on each route, the counterpart of wrapping a Go handler in `RequireAuth(...)`. They run before the handler reads the body, preserving Go's ordering (401 before 400).

## Alternatives considered
- **Pydantic request models:** idiomatic FastAPI, but they produce 422s with a different error shape, coerce types (`"5"` → `5`), and can't express Go's "unknown field → error" plus "null means not provided" rules without a lot of custom config. A tiny schema-based decoder was simpler and exact.
- **Starlette only (no FastAPI):** equally capable, but FastAPI's dependency injection makes the auth/admin/state wiring clearer for little cost.

## Consequences
- Route registration stays flat and readable. A new route needs a router function plus, if it takes a body, a `body.decode` schema.
- FastAPI's automatic OpenAPI docs are deliberately unavailable. The README's API table and `features/` are the reference.
