"""Admin-only routes (Go: admin_handler.go). Non-admins get 403 - here the
gatekeeping *is* the point, unlike the 404s used for ownership checks."""

from fastapi import APIRouter, Depends

from ..errors import ApiError, json_response
from ..jsonfmt import ZERO_TIME
from ..models import User
from ..security import require_admin
from ..state import AppState, get_state

router = APIRouter()


@router.get("/api/admin/users")
def list_users(admin: User = Depends(require_admin), state: AppState = Depends(get_state)):
    return json_response(200, [u.public() for u in state.users.list()])


@router.post("/api/admin/users/{id}/unlock")
def unlock_user(id: str, admin: User = Depends(require_admin), state: AppState = Depends(get_state)):
    user = state.users.get(id)
    if user is None:
        raise ApiError(404, "not_found", "user not found")
    user.failed_login_count = 0
    user.locked_until = ZERO_TIME
    state.users.put(user.id, user)
    return json_response(200, user.public())
