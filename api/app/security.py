"""Authentication/authorization dependencies - the counterparts of the Go
API's RequireAuth and RequireAdmin middleware, with byte-identical 401/403
bodies. Declared on a route, they run before the handler touches the body."""

from fastapi import Depends, Request

from .auth import tokens
from .errors import ApiError
from .models import User
from .state import AppState, get_state

UNAUTHORIZED = ApiError(401, "unauthorized", "missing or invalid token")


def require_user(request: Request, state: AppState = Depends(get_state)) -> User:
    """Extract and verify the bearer token and load its user, or 401."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise UNAUTHORIZED
    try:
        claims = tokens.verify(state.secret, header[len("Bearer "):])
    except tokens.TokenError:
        raise UNAUTHORIZED
    user = state.users.get(claims.user_id)
    if user is None:
        raise UNAUTHORIZED
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    """Applied on top of require_user; rejects non-admins with 403."""
    if not user.is_admin:
        raise ApiError(403, "forbidden", "admin access required")
    return user
