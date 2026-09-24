"""Task routes (Go: tasks_handler.go). PUT is a partial update: fields that
are absent or null are left unchanged."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Request

from .. import body
from ..errors import ApiError, json_response, no_content
from ..idgen import new_id
from ..jsonfmt import now, parse_time
from ..models import STATUS_TODO, VALID_STATUSES, Task, User
from ..security import require_user
from ..state import AppState, get_state
from . import raw_body

router = APIRouter()

TASK_SCHEMA = {
    "board_id": body.STR,
    "title": body.OPT_STR,
    "description": body.OPT_STR,
    "status": body.OPT_STR,
    "due_date": body.OPT_STR,
    "label_ids": body.OPT_STR_LIST,
}


def parse_due_date(raw: str) -> datetime | None:
    """An empty string means "no due date" (None); anything else must be a
    valid RFC3339 timestamp or ValueError is raised."""
    if not raw.strip():
        return None
    return parse_time(raw)


def _due_date(raw: str) -> datetime | None:
    try:
        return parse_due_date(raw)
    except ValueError:
        raise ApiError(400, "invalid_due_date", "due date must be a valid RFC3339 timestamp")


def _status(raw: str) -> str:
    if raw not in VALID_STATUSES:
        raise ApiError(400, "invalid_status", "status must be todo, in_progress, or done")
    return raw


def _validate_label_ids(state: AppState, ids: list[str], board_id: str, user_id: str) -> None:
    """Every id must name a label that belongs to board_id and user_id."""
    for id in ids:
        label = state.labels.get(id)
        if label is None or label.board_id != board_id or label.user_id != user_id:
            raise ApiError(400, "invalid_label", "one or more label ids are invalid for this board")


@router.get("/api/tasks")
def list_tasks(request: Request, user: User = Depends(require_user), state: AppState = Depends(get_state)):
    board_id = request.query_params.get("board_id", "")
    tasks = state.tasks.list_by_board(user.id, board_id) if board_id else state.tasks.list_by_user(user.id)
    return json_response(200, [t.to_dict() for t in tasks])


@router.post("/api/tasks")
def create_task(
    user: User = Depends(require_user), raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)
):
    req = body.decode(raw, TASK_SCHEMA)
    if req["title"] is None or not req["title"].strip():
        raise ApiError(400, "invalid_title", "task title is required")

    board = state.boards.get(req["board_id"])
    if board is None or board.user_id != user.id:
        raise ApiError(400, "invalid_board", "board not found")

    status = _status(req["status"]) if req["status"] is not None else STATUS_TODO
    description = req["description"] if req["description"] is not None else ""
    due_date = _due_date(req["due_date"]) if req["due_date"] is not None else None

    label_ids: list[str] = []
    if req["label_ids"] is not None:
        _validate_label_ids(state, req["label_ids"], board.id, user.id)
        label_ids = req["label_ids"]

    ts = now()
    task = Task(
        id=new_id(), user_id=user.id, board_id=board.id, title=req["title"], description=description,
        status=status, due_date=due_date, label_ids=label_ids, created_at=ts, updated_at=ts,
    )
    state.tasks.put(task.id, task)
    return json_response(201, task.to_dict())


def _owned_task(state: AppState, user: User, id: str) -> Task:
    task = state.tasks.get(id)
    if task is None or task.user_id != user.id:
        raise ApiError(404, "not_found", "task not found")
    return task


@router.put("/api/tasks/{id}")
def update_task(
    id: str, user: User = Depends(require_user), raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)
):
    task = _owned_task(state, user, id)
    req = body.decode(raw, TASK_SCHEMA)

    # Validate everything before applying anything, so a rejected request
    # never leaves a partially-updated task in memory (the Go handler
    # mutates a copy for the same effect).
    if req["title"] is not None and not req["title"].strip():
        raise ApiError(400, "invalid_title", "task title cannot be empty")
    status = _status(req["status"]) if req["status"] is not None else None
    due_date = _due_date(req["due_date"]) if req["due_date"] is not None else None
    if req["label_ids"] is not None:
        # Validated against the task's current board - a request that both
        # reassigns the board and sets label_ids would validate against the
        # old board. Not reachable from the frontend (TaskForm never
        # reassigns boards); same documented edge case as the Go API.
        _validate_label_ids(state, req["label_ids"], task.board_id, user.id)
    new_board_id = None
    if req["board_id"] and req["board_id"] != task.board_id:
        board = state.boards.get(req["board_id"])
        if board is None or board.user_id != user.id:
            raise ApiError(400, "invalid_board", "board not found")
        new_board_id = board.id

    if req["title"] is not None:
        task.title = req["title"]
    if req["description"] is not None:
        task.description = req["description"]
    if status is not None:
        task.status = status
    if req["due_date"] is not None:
        task.due_date = due_date
    if req["label_ids"] is not None:
        task.label_ids = req["label_ids"]
    if new_board_id is not None:
        task.board_id = new_board_id
    task.updated_at = now()

    state.tasks.put(task.id, task)
    return json_response(200, task.to_dict())


@router.delete("/api/tasks/{id}")
def delete_task(id: str, user: User = Depends(require_user), state: AppState = Depends(get_state)):
    task = _owned_task(state, user, id)
    for att in state.attachments.list_by_task(task.id):
        state.attachments.delete_blob(att.id)
        state.attachments.delete(att.id)
    state.tasks.delete(task.id)
    return no_content()
