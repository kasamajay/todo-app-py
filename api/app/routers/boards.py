"""Board routes (Go: boards_handler.go). Ownership failures return 404, not
403, so non-owners can't confirm a board exists."""

from fastapi import APIRouter, Depends

from .. import body
from ..errors import ApiError, json_response, no_content
from ..idgen import new_id
from ..jsonfmt import now
from ..models import Board, User
from ..security import require_user
from ..state import AppState, get_state
from . import raw_body

router = APIRouter()

BOARD_SCHEMA = {"name": body.STR, "summary": body.STR, "start_date": body.STR}


@router.get("/api/boards")
def list_boards(user: User = Depends(require_user), state: AppState = Depends(get_state)):
    return json_response(200, [b.to_dict() for b in state.boards.list_by_user(user.id)])


@router.post("/api/boards")
def create_board(
    user: User = Depends(require_user), raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)
):
    req = body.decode(raw, BOARD_SCHEMA)
    if not req["name"].strip():
        raise ApiError(400, "invalid_name", "board name is required")

    ts = now()
    board = Board(
        id=new_id(), user_id=user.id, name=req["name"], summary=req["summary"],
        start_date=req["start_date"], created_at=ts, updated_at=ts,
    )
    state.boards.put(board.id, board)
    return json_response(201, board.to_dict())


def _owned_board(state: AppState, user: User, id: str) -> Board:
    board = state.boards.get(id)
    if board is None or board.user_id != user.id:
        raise ApiError(404, "not_found", "board not found")
    return board


@router.put("/api/boards/{id}")
def update_board(
    id: str, user: User = Depends(require_user), raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)
):
    board = _owned_board(state, user, id)
    req = body.decode(raw, BOARD_SCHEMA)
    if not req["name"].strip():
        raise ApiError(400, "invalid_name", "board name is required")

    board.name = req["name"]
    board.summary = req["summary"]
    board.start_date = req["start_date"]
    board.updated_at = now()
    state.boards.put(board.id, board)
    return json_response(200, board.to_dict())


@router.delete("/api/boards/{id}")
def delete_board(id: str, user: User = Depends(require_user), state: AppState = Depends(get_state)):
    board = _owned_board(state, user, id)

    # Cascade (decisions/0006): every task on this board and every attachment
    # on each of those tasks (metadata + blob), then the board's labels.
    for task in state.tasks.list_by_board_any(board.id):
        for att in state.attachments.list_by_task(task.id):
            state.attachments.delete_blob(att.id)
            state.attachments.delete(att.id)
        state.tasks.delete(task.id)
    for label in state.labels.list_by_board_any(board.id):
        state.labels.delete(label.id)

    state.boards.delete(board.id)
    return no_content()
