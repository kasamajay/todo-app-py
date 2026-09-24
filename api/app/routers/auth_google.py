"""Sign in with Google - OAuth 2.0 Authorization Code flow (Go:
auth_google_handler.go, decisions/0010)."""

from __future__ import annotations

import logging
from urllib.parse import quote_plus

from fastapi import APIRouter, Depends, Request
from starlette.responses import RedirectResponse

from ..auth import google
from ..errors import ApiError
from ..idgen import new_id
from ..jsonfmt import now
from ..models import User
from ..state import AppState, get_state
from .auth import issue_two_factor_challenge, mint

log = logging.getLogger("todo-app")
router = APIRouter()

GOOGLE_STATE_COOKIE = "google_oauth_state"
GOOGLE_STATE_PATH = "/api/auth/google"
GOOGLE_STATE_TTL_SECONDS = 5 * 60


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url, status_code=302)


@router.get("/api/auth/google/login")
def google_login(state: AppState = Depends(get_state)):
    """Set a short-lived CSRF state cookie and redirect to Google's consent screen."""
    cfg = state.config
    if not cfg.google_configured:
        raise ApiError(503, "google_oauth_not_configured", "Google sign-in is not configured on this server")

    oauth_state = google.random_state()
    resp = _redirect(google.google_auth_url(cfg.google_client_id, cfg.google_redirect_uri, oauth_state))
    resp.set_cookie(
        GOOGLE_STATE_COOKIE,
        oauth_state,
        max_age=GOOGLE_STATE_TTL_SECONDS,
        path=GOOGLE_STATE_PATH,
        httponly=True,
        samesite="lax",
    )
    return resp


@router.get("/api/auth/google/callback")
def google_callback(request: Request, state: AppState = Depends(get_state)):
    """Exchange the code for an access token, fetch the Google profile,
    resolve it to a local account (by Google ID, then auto-link by verified
    email, then create), and redirect back to the frontend with the app
    token in the URL fragment (never a query param, so it never reaches
    server access logs)."""
    cfg = state.config
    q = request.query_params
    clear_cookie = False

    def done(url: str) -> RedirectResponse:
        resp = _redirect(url)
        if clear_cookie:
            resp.delete_cookie(GOOGLE_STATE_COOKIE, path=GOOGLE_STATE_PATH)
        return resp

    def fail(code: str) -> RedirectResponse:
        return done(cfg.frontend_base_url + "/#google_error=" + quote_plus(code))

    if not cfg.google_configured:
        return fail("google_oauth_not_configured")
    if q.get("error", ""):
        return fail("google_denied")

    cookie = request.cookies.get(GOOGLE_STATE_COOKIE, "")
    # One-time use: clear the state cookie regardless of outcome from here on.
    clear_cookie = True
    if not cookie:
        return fail("google_state_missing")
    oauth_state = q.get("state", "")
    if not oauth_state or oauth_state != cookie:
        return fail("google_state_mismatch")

    code = q.get("code", "")
    if not code:
        return fail("google_missing_code")

    try:
        access_token = google.exchange_google_code(
            cfg.google_client_id, cfg.google_client_secret, cfg.google_redirect_uri, code
        )
    except google.GoogleError as e:
        log.error("google token exchange failed: %s", e)
        return fail("google_exchange_failed")

    try:
        profile = google.fetch_google_user_info(access_token)
    except google.GoogleError as e:
        log.error("google userinfo fetch failed: %s", e)
        return fail("google_userinfo_failed")
    if not profile.email or not profile.email_verified:
        return fail("google_email_unverified")

    email = profile.email.strip().lower()

    user = state.users.find_by_google_id(profile.sub)
    if user is None:
        existing = state.users.find_by_email(email)
        try:
            if existing is not None:
                # Auto-link: Google has already verified this email, so treat
                # it as the same account rather than creating a duplicate.
                existing.google_id = profile.sub
                state.users.put(existing.id, existing)
                user = existing
            else:
                user = User(id=new_id(), email=email, google_id=profile.sub, created_at=now())
                state.users.put(user.id, user)
        except OSError:
            return fail("google_internal_error")

    if user.is_locked():
        return fail("google_account_locked")

    if user.two_factor_enabled:
        try:
            updated = issue_two_factor_challenge(state, user)
        except OSError:
            return fail("google_internal_error")
        return done(cfg.frontend_base_url + "/#google_2fa_required=" + quote_plus(updated.id))

    return done(cfg.frontend_base_url + "/#google_token=" + quote_plus(mint(state, user)))
