"""One module per resource, mirroring todo-app's api/internal/handlers/*.go."""

from fastapi import Request


async def raw_body(request: Request) -> bytes:
    """Dependency giving sync handlers the raw request body to decode with
    body.decode (they run in FastAPI's threadpool and can't await it)."""
    return await request.body()
