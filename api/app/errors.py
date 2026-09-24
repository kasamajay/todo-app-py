"""Response helpers and error handling. Every error body has the same shape
the Go API's writeError produces - {"error":{"code":...,"message":...}} -
and FastAPI's own defaults (422 validation errors, JSON 404s, redirects on
trailing slashes) are overridden so none of them leak through."""

from __future__ import annotations

import json
import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import PlainTextResponse, Response

log = logging.getLogger("todo-app")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def json_response(status: int, body) -> Response:
    """Like Go's writeJSON: compact JSON + trailing newline, Content-Type
    application/json (no charset parameter)."""
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":")) + "\n"
    return Response(content=content.encode("utf-8"), status_code=status, headers={"content-type": "application/json"})


def error_response(status: int, code: str, message: str) -> Response:
    return json_response(status, {"error": {"code": code, "message": message}})


def no_content() -> Response:
    return Response(status_code=204)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return error_response(exc.status, exc.code, exc.message)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        # Unmatched routes/methods: reproduce Go's http.ServeMux plain-text
        # responses rather than FastAPI's {"detail": ...} JSON.
        if exc.status_code == 405:
            return PlainTextResponse("Method Not Allowed\n", status_code=405, headers=exc.headers)
        if exc.status_code == 404:
            return PlainTextResponse("404 page not found\n", status_code=404)
        return error_response(exc.status_code, "error", str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        # Handlers parse bodies themselves (see body.py), so this only fires
        # for malformed path/query params - treat it like a bad body.
        return error_response(400, "invalid_body", "request body must be valid JSON")

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        # Counterpart of Go's Recover middleware: log and return a 500
        # instead of dropping the connection.
        log.exception("panic handling %s %s: %s", request.method, request.url.path, exc)
        return error_response(500, "internal_error", "internal server error")
