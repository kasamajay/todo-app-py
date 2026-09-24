"""Label routes (Go: labels_handler.go). Labels are per-board, colour from a
fixed palette."""

from fastapi import APIRouter, Depends, Request

from .. import body
from ..errors import ApiError, json_response, no_content
from ..idgen import new_id
from ..jsonfmt import now
from ..models import Label, User, is_valid_label_color
from ..security import require_user
from ..state import AppState, get_state
from . import raw_body

router = APIRouter()

LABEL_SCHEMA = {"board_id": body.STR, "name": body.STR, "color": body.STR}


def _validate(req: dict) -> None:
    if not req["name"].strip():
        raise ApiError(400, "invalid_name", "label name is required")
    if not is_valid_label_color(req["color"]):
        raise ApiError(400, "invalid_color", "color must be one of the allowed label colors")


@router.get("/api/labels")
def list_labels(request: Request, user: User = Depends(require_user), state: AppState = Depends(get_state)):
    board_id = request.query_params.get("board_id", "")
    if not board_id:
        raise ApiError(400, "invalid_board", "board_id is required")
    board = state.boards.get(board_id)
    if board is None or board.user_id != user.id:
        raise ApiError(400, "invalid_board", "board not found")
    return json_response(200, [l.to_dict() for l in state.labels.list_by_board(user.id, board_id)])


@router.post("/api/labels")
def create_label(
    user: User = Depends(require_user), raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)
):
    req = body.decode(raw, LABEL_SCHEMA)
    board = state.boards.get(req["board_id"])
    if board is None or board.user_id != user.id:
        raise ApiError(400, "invalid_board", "board not found")
    _validate(req)

    label = Label(id=new_id(), user_id=user.id, board_id=board.id, name=req["name"], color=req["color"], created_at=now())
    state.labels.put(label.id, label)
    return json_response(201, label.to_dict())


def _owned_label(state: AppState, user: User, id: str) -> Label:
    label = state.labels.get(id)
    if label is None or label.user_id != user.id:
        raise ApiError(404, "not_found", "label not found")
    return label


@router.put("/api/labels/{id}")
def update_label(
    id: str, user: User = Depends(require_user), raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)
):
    label = _owned_label(state, user, id)
    req = body.decode(raw, LABEL_SCHEMA)
    _validate(req)

    label.name = req["name"]
    label.color = req["color"]
    state.labels.put(label.id, label)
    return json_response(200, label.to_dict())


@router.delete("/api/labels/{id}")
def delete_label(id: str, user: User = Depends(require_user), state: AppState = Depends(get_state)):
    label = _owned_label(state, user, id)

    # Cascade: strip this label from every task that references it rather
    # than deleting those tasks (decisions/0006 - no dangling references,
    # but the referencing resource itself shouldn't disappear).
    for task in state.tasks.list_by_board_any(label.board_id):
        if label.id not in task.label_ids:
            continue
        task.label_ids.remove(label.id)
        task.updated_at = now()
        state.tasks.put(task.id, task)

    state.labels.delete(label.id)
    return no_content()
