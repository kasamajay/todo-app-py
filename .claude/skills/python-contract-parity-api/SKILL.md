---
name: python-contract-parity-api
description: >
  Conventions for api/ in todo-app-py: a FastAPI port that must stay
  byte-compatible with todo-app's Go API (same routes, status codes, error
  bodies, JSON field order/omission, time format, cookies, redirects, data
  files and token format) because the React frontend is shared unchanged.
  Use when adding or changing an endpoint, a model field, request decoding,
  error handling or storage, or when a response "looks slightly different"
  from the Go backend.
---

# Python API with Go-contract parity (todo-app-py)

## Overview

`web/` is identical to todo-app's, so the API's HTTP behaviour **is** the spec. Every handler in `api/app/routers/` mirrors a Go handler in `../todo-app/api/internal/handlers/`: the same check order, error codes and messages. The on-disk JSON and the tokens are interchangeable with the Go backend. See `../../../decisions/0014-python-fastapi-port.md`.

## Rules

- **Responses:** return `errors.json_response(status, dict)` or raise `errors.ApiError(status, code, message)`. Don't return dicts or Pydantic models for FastAPI to serialize, because that changes the content type, spacing and error shape.
- **Request bodies:** declare a schema and call `body.decode(raw, {...})` with `raw: bytes = Depends(raw_body)`. Don't use Pydantic body models. Use `STR`/`BOOL` for Go value fields (null → zero value) and `OPT_STR`/`OPT_STR_LIST` for Go pointer fields (null/absent → `None` = "not provided"). Unknown fields and wrong types are 400 `invalid_body`, as Go's `DisallowUnknownFields` does.
- **Models:** field order in `to_dict` is the Go struct order.
  - `omitempty` strings, ints and slices are left out when empty.
  - Times are always emitted, including the zero time `0001-01-01T00:00:00Z`, via `jsonfmt.format_time`.
  - `bytes` becomes base64, and `None` becomes `null`.
  - A new field needs a matching change in the Go model if both backends should keep sharing data.
- **Storage:** `Store` returns deep copies. Fetch, mutate, then `put()`. Validate everything *before* mutating, so a rejected request never persists partial changes. Run exactly **one** uvicorn worker, because the store is in-memory and assumes a single writer.
- **Auth:** protect a route with `Depends(require_user)` or `Depends(require_admin)`. Ownership failures are **404** (never confirm existence); admin gatekeeping is 403.
- **Logging:** keep the wording of the lines users grep for (admin bootstrap, `password reset requested for …`, `two-factor code requested for …`).

## Checking parity

```
docker compose run --rm api pytest            # includes tests/test_parity.py
# contract suite against a running API on throwaway data (see docker-dev-workflow):
docker compose run --rm --no-deps -e CONTRACT_BASE_URL=http://host.docker.internal:8080 api pytest tests/contract
```

Run the contract suite against **both** backends after any behaviour change. If only one passes, they've diverged.
