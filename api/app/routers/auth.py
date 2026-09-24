"""Password auth, password reset, and two-factor routes (Go: auth_handler.go)."""

from __future__ import annotations

import logging
import threading
from datetime import timedelta

from fastapi import APIRouter, Depends

from .. import body
from ..auth import passwords, tokens
from ..auth.twofactor import generate_six_digit_code
from ..errors import ApiError, error_response, json_response, no_content
from ..idgen import new_id
from ..jsonfmt import ZERO_TIME, format_time, now
from ..models import User
from ..security import require_user
from ..state import AppState, get_state
from . import raw_body

log = logging.getLogger("todo-app")
router = APIRouter()

MAX_FAILED_LOGINS = 3
LOCK_DURATION = timedelta(minutes=30)
RESET_TOKEN_TTL = timedelta(hours=1)
MIN_PASSWORD_LENGTH = 8

TWO_FACTOR_CODE_TTL = timedelta(minutes=10)
TWO_FACTOR_MAX_ATTEMPTS = 5

_dummy_lock = threading.Lock()
_dummy: tuple[bytes, bytes] | None = None


def _dummy_login_params() -> tuple[bytes, bytes]:
    """A fixed salt/hash pair used when the submitted email doesn't match a
    user (or the account has no password), so PBKDF2 still runs at the same
    cost as a real login and response timing can't reveal account existence."""
    global _dummy
    with _dummy_lock:
        if _dummy is None:
            dummy_hash, _ = passwords.hash_password("dummy-password-for-timing-only")
            _dummy = (b"fixed-dummy-salt-16b", dummy_hash)
        return _dummy


def mint(state: AppState, user: User) -> str:
    return tokens.mint(state.secret, tokens.Claims(user.id, user.is_admin, now() + tokens.TOKEN_TTL))


def _password_len(p: str) -> int:
    # Go's len() on a string counts UTF-8 bytes, not characters.
    return len(p.encode("utf-8"))


@router.post("/api/auth/register")
def register(raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)):
    req = body.decode(raw, {"email": body.STR, "password": body.STR})

    email = req["email"].strip().lower()
    if not email or "@" not in email:
        raise ApiError(400, "invalid_email", "a valid email is required")
    if _password_len(req["password"]) < MIN_PASSWORD_LENGTH:
        raise ApiError(400, "invalid_password", "password must be at least 8 characters")
    if state.users.find_by_email(email) is not None:
        raise ApiError(409, "email_taken", "an account with that email already exists")

    hash_, salt = passwords.hash_password(req["password"])
    user = User(id=new_id(), email=email, password_hash=hash_, salt=salt, created_at=now())
    state.users.put(user.id, user)

    return json_response(201, {"token": mint(state, user), "user": user.public()})


@router.post("/api/auth/login")
def login(raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)):
    req = body.decode(raw, {"email": body.STR, "password": body.STR})
    email = req["email"].strip().lower()

    user = state.users.find_by_email(email)
    has_password = user is not None and bool(user.password_hash)
    if has_password:
        salt, hash_ = user.salt, user.password_hash
    else:
        salt, hash_ = _dummy_login_params()

    # Always run PBKDF2 - found or not, password set or not - so response
    # timing doesn't reveal whether the email is registered or is a
    # Google-only account with no password set.
    match = passwords.verify_password(req["password"], hash_, salt)

    if not has_password:
        raise ApiError(401, "invalid_credentials", "invalid email or password")

    if user.is_locked():
        raise ApiError(403, "account_locked", "account is locked, try again later")

    if not match:
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now() + LOCK_DURATION
        try:
            state.users.put(user.id, user)
        except OSError as e:
            log.error("failed to persist failed login count for %s: %s", user.id, e)
        raise ApiError(401, "invalid_credentials", "invalid email or password")

    user.failed_login_count = 0
    user.locked_until = ZERO_TIME
    state.users.put(user.id, user)

    if user.two_factor_enabled:
        updated = issue_two_factor_challenge(state, user)
        return json_response(200, {"two_factor_required": True, "user_id": updated.id})

    return json_response(200, {"token": mint(state, user), "user": user.public()})


@router.post("/api/auth/logout")
def logout(user: User = Depends(require_user)):
    # Tokens are stateless HMAC tokens with no server-side session store, so
    # logout is a client-side discard - there is nothing to revoke here.
    return no_content()


@router.get("/api/auth/me")
def me(user: User = Depends(require_user)):
    return json_response(200, user.public())


@router.post("/api/auth/forgot-password")
def forgot_password(raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)):
    req = body.decode(raw, {"email": body.STR})

    user = state.users.find_by_email(req["email"].strip().lower())
    if user is not None:
        user.reset_token = new_id()
        user.reset_token_expires = now() + RESET_TOKEN_TTL
        try:
            state.users.put(user.id, user)
        except OSError:
            pass
        else:
            # No email infrastructure exists in this project (decisions/0007),
            # so the reset token is logged server-side instead of emailed.
            log.info(
                "password reset requested for %s: reset_token=%s (expires %s)",
                user.email, user.reset_token, _rfc3339(user.reset_token_expires),
            )

    # Always 200 regardless of whether the email exists, so this endpoint
    # can't be used to enumerate registered accounts.
    return json_response(200, {"message": "if that email exists, a reset link has been sent"})


@router.post("/api/auth/reset-password")
def reset_password(raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)):
    req = body.decode(raw, {"token": body.STR, "new_password": body.STR})
    if _password_len(req["new_password"]) < MIN_PASSWORD_LENGTH:
        raise ApiError(400, "invalid_password", "password must be at least 8 characters")

    user = state.users.find_by_reset_token(req["token"])
    if user is None or not req["token"] or now() > user.reset_token_expires:
        raise ApiError(400, "invalid_token", "reset token is invalid or expired")

    user.password_hash, user.salt = passwords.hash_password(req["new_password"])
    user.reset_token = ""
    user.reset_token_expires = ZERO_TIME
    user.failed_login_count = 0
    user.locked_until = ZERO_TIME
    state.users.put(user.id, user)

    return json_response(200, {"message": "password has been reset"})


def issue_two_factor_challenge(state: AppState, user: User) -> User:
    """Generate a 6-digit code, persist it with a short expiry, and log it
    server-side instead of emailing it (decisions/0007, 0011). Shared by
    login and the Google callback, which must gate on 2FA identically."""
    user.two_factor_code = generate_six_digit_code()
    user.two_factor_code_expires = now() + TWO_FACTOR_CODE_TTL
    user.two_factor_attempts = 0
    state.users.put(user.id, user)
    log.info(
        "two-factor code requested for %s: code=%s (expires %s)",
        user.email, user.two_factor_code, _rfc3339(user.two_factor_code_expires),
    )
    return user


def _clear_two_factor(user: User) -> None:
    user.two_factor_code = ""
    user.two_factor_code_expires = ZERO_TIME
    user.two_factor_attempts = 0


@router.post("/api/auth/2fa/verify")
def verify_two_factor(raw: bytes = Depends(raw_body), state: AppState = Depends(get_state)):
    """Completes a login put on hold by issue_two_factor_challenge. Public
    route (the caller isn't fully authenticated yet), gated by the code
    itself plus a small attempt budget rather than a bearer token."""
    req = body.decode(raw, {"user_id": body.STR, "code": body.STR})
    user_id, code = req["user_id"].strip(), req["code"].strip()
    if not user_id or not code:
        raise ApiError(400, "invalid_body", "user_id and code are required")

    user = state.users.get(user_id)
    if user is None or not user.two_factor_code:
        raise ApiError(401, "two_factor_not_pending", "no verification code is pending for this account")

    if now() > user.two_factor_code_expires:
        _clear_two_factor(user)
        try:
            state.users.put(user.id, user)
        except OSError as e:
            log.error("failed to clear expired two-factor code for %s: %s", user.id, e)
        raise ApiError(401, "two_factor_code_expired", "verification code has expired, please log in again")

    if code != user.two_factor_code:
        user.two_factor_attempts += 1
        if user.two_factor_attempts >= TWO_FACTOR_MAX_ATTEMPTS:
            _clear_two_factor(user)
            try:
                state.users.put(user.id, user)
            except OSError as e:
                log.error("failed to invalidate two-factor code for %s: %s", user.id, e)
            raise ApiError(401, "two_factor_too_many_attempts", "too many incorrect attempts, please log in again")
        try:
            state.users.put(user.id, user)
        except OSError as e:
            log.error("failed to persist two-factor attempt count for %s: %s", user.id, e)
        raise ApiError(401, "two_factor_code_incorrect", "incorrect verification code")

    _clear_two_factor(user)
    state.users.put(user.id, user)
    return json_response(200, {"token": mint(state, user), "user": user.public()})


@router.put("/api/auth/2fa")
def update_two_factor(
    ctx_user: User = Depends(require_user),
    raw: bytes = Depends(raw_body),
    state: AppState = Depends(get_state),
):
    """Enable/disable 2FA on the caller's own account - opt-in only, no admin
    override (decisions/0011)."""
    req = body.decode(raw, {"enabled": body.BOOL})

    user = state.users.get(ctx_user.id)
    if user is None:
        return error_response(401, "unauthorized", "account not found")
    user.two_factor_enabled = req["enabled"]
    if not req["enabled"]:
        _clear_two_factor(user)
    state.users.put(user.id, user)
    return json_response(200, user.public())


def _rfc3339(t) -> str:
    # Go's time.RFC3339 (whole seconds), used in the logged expiry times.
    return format_time(t.replace(microsecond=0))
