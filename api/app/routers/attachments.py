"""Attachment routes (Go: attachments_handler.go). Blobs live under
data/attachments/<id>, metadata in attachments.json. 10MB per file."""

from __future__ import annotations

import posixpath

from fastapi import APIRouter, Depends, Request
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.responses import Response

from ..errors import ApiError, json_response, no_content
from ..idgen import new_id
from ..jsonfmt import now
from ..models import Attachment, Task, User
from ..security import require_user
from ..sniff import detect_content_type
from ..state import AppState, get_state

router = APIRouter()

MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10MB
MULTIPART_OVERHEAD = 1024  # small margin, as in the Go handler's MaxBytesReader

TOO_LARGE = ApiError(413, "file_too_large", "attachment exceeds the 10MB limit")


def _owned_task(state: AppState, user: User, task_id: str) -> Task:
    task = state.tasks.get(task_id)
    if task is None or task.user_id != user.id:
        raise ApiError(404, "not_found", "task not found")
    return task


async def _read_body_limited(request: Request, limit: int) -> bytes:
    """Read the request body, failing as soon as it exceeds limit bytes
    (the counterpart of Go's http.MaxBytesReader)."""
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > limit:
        raise TOO_LARGE
    chunks, total = [], 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > limit:
            raise TOO_LARGE
        chunks.append(chunk)
    return b"".join(chunks)


async def _parse_multipart(request: Request, raw: bytes):
    async def once():
        yield raw

    # max_part_size bounds non-file fields; the file itself is checked below.
    parser = MultiPartParser(request.headers, once(), max_files=1000, max_fields=1000)
    return await parser.parse()


@router.post("/api/tasks/{id}/attachments")
async def upload_attachment(
    id: str, request: Request, user: User = Depends(require_user), state: AppState = Depends(get_state)
):
    task = await run_in_threadpool(_owned_task, state, user, id)

    raw = await _read_body_limited(request, MAX_ATTACHMENT_BYTES + MULTIPART_OVERHEAD)
    content_type_header = request.headers.get("content-type", "")
    if not content_type_header.lower().startswith("multipart/form-data"):
        # Go's ParseMultipartForm fails on a non-multipart body, and the
        # handler reports every parse failure as 413.
        raise TOO_LARGE
    try:
        form = await _parse_multipart(request, raw)
    except (MultiPartException, ValueError, KeyError):
        raise TOO_LARGE

    upload = form.get("file")
    if not isinstance(upload, UploadFile):
        raise ApiError(400, "invalid_file", "a 'file' form field is required")
    try:
        content = await upload.read(MAX_ATTACHMENT_BYTES + 1)
    finally:
        await upload.close()
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise TOO_LARGE

    content_type = upload.headers.get("content-type", "") or detect_content_type(content)
    # Go's multipart.FileHeader.Filename is the base name of the part's filename.
    filename = posixpath.basename(upload.filename or "")

    attachment = Attachment(
        id=new_id(), task_id=task.id, user_id=user.id, filename=filename,
        content_type=content_type, size_bytes=len(content), created_at=now(),
    )

    def store():
        state.attachments.write_blob(attachment.id, content)
        try:
            state.attachments.put(attachment.id, attachment)
        except BaseException:
            state.attachments.delete_blob(attachment.id)
            raise

    try:
        await run_in_threadpool(store)
    except OSError:
        raise ApiError(500, "internal_error", "failed to store attachment")
    return json_response(201, attachment.to_dict())


@router.get("/api/tasks/{id}/attachments")
def list_attachments(id: str, user: User = Depends(require_user), state: AppState = Depends(get_state)):
    task = _owned_task(state, user, id)
    return json_response(200, [a.to_dict() for a in state.attachments.list_by_task(task.id)])


def _owned_attachment(state: AppState, task: Task, aid: str) -> Attachment:
    attachment = state.attachments.get(aid)
    if attachment is None or attachment.task_id != task.id:
        raise ApiError(404, "not_found", "attachment not found")
    return attachment


@router.get("/api/tasks/{id}/attachments/{aid}")
def download_attachment(id: str, aid: str, user: User = Depends(require_user), state: AppState = Depends(get_state)):
    task = _owned_task(state, user, id)
    attachment = _owned_attachment(state, task, aid)
    try:
        content = state.attachments.read_blob(attachment.id)
    except OSError:
        raise ApiError(404, "not_found", "attachment content not found")

    # Headers set explicitly (not via media_type) so Starlette doesn't append
    # "; charset=utf-8" to text/* types the way Go wouldn't.
    return Response(
        content=content,
        status_code=200,
        headers={
            "content-type": attachment.content_type,
            "content-disposition": f'inline; filename="{attachment.filename}"',
        },
    )


@router.delete("/api/tasks/{id}/attachments/{aid}")
def delete_attachment(id: str, aid: str, user: User = Depends(require_user), state: AppState = Depends(get_state)):
    task = _owned_task(state, user, id)
    attachment = _owned_attachment(state, task, aid)
    try:
        state.attachments.delete_blob(attachment.id)
    except OSError:
        raise ApiError(500, "internal_error", "failed to delete attachment content")
    state.attachments.delete(attachment.id)
    return no_content()
