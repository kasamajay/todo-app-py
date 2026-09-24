"""The todo-app-py API server: a FastAPI app exposing exactly the same HTTP
contract as todo-app's Go API (api/cmd/api/main.go), so the unchanged React
frontend works against either backend.

Run with a single uvicorn worker - the JSON stores keep in-memory state and
assume one writer process (see decisions/0004 and 0014):

    uvicorn app.main:app --host 0.0.0.0 --port 8080 [--reload]
"""

from __future__ import annotations

import logging
import os
import sys
import time

from fastapi import FastAPI, Request

from .bootstrap import bootstrap_admin
from .config import Config
from .errors import install_error_handlers
from .routers import admin, attachments, auth, auth_google, boards, labels, tasks
from .state import AppState

log = logging.getLogger("todo-app")


def _configure_logging() -> None:
    # Same line format as Go's log package ("2006/01/02 15:04:05 message").
    if log.handlers:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s", datefmt="%Y/%m/%d %H:%M:%S"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def _format_duration(seconds: float) -> str:
    # Roughly Go's time.Duration.String() for sub-second request timings.
    if seconds >= 1:
        return f"{seconds:.6g}s"
    if seconds >= 1e-3:
        return f"{seconds * 1e3:.6g}ms"
    return f"{seconds * 1e6:.6g}µs"


def create_app(config: Config | None = None) -> FastAPI:
    _configure_logging()
    config = config or Config.from_env()
    if not config.google_configured:
        log.info(
            "Google OAuth not configured (GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET unset) - Sign in with Google is disabled"
        )

    state = AppState.load(config)
    bootstrap_admin(state.users)

    # No OpenAPI/docs routes and no trailing-slash redirects: the route table
    # is exactly the Go API's, and anything else gets Go's plain-text 404.
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, redirect_slashes=False)
    app.state.todo = state
    install_error_handlers(app)

    for module in (auth, auth_google, boards, tasks, labels, attachments, admin):
        app.include_router(module.router)

    @app.middleware("http")
    async def logging_middleware(request: Request, call_next):
        start = time.perf_counter()
        response = await call_next(request)
        log.info(
            "%s %s %d %s", request.method, request.url.path, response.status_code,
            _format_duration(time.perf_counter() - start),
        )
        return response

    addr = os.environ.get("ADDR") or ":8080"
    log.info("todo-app api listening on %s (data dir: %s)", addr, config.data_dir)
    return app


app = None if os.environ.get("TODO_APP_NO_AUTOCREATE") else create_app()
