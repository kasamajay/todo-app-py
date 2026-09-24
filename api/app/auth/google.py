"""Google OAuth 2.0 Authorization Code flow helpers (decisions/0010). The
token exchange and userinfo fetch are plain HTTPS calls - no JWT or JWKS
parsing is needed since Google's servers do that verification."""

from __future__ import annotations

import base64
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

_TIMEOUT = httpx.Timeout(10.0)


class GoogleError(Exception):
    pass


@dataclass
class GoogleUserInfo:
    sub: str
    email: str
    email_verified: bool


def random_state() -> str:
    """A URL-safe random value for the OAuth CSRF state parameter. It carries
    no claims, so it isn't HMAC-signed - its unguessability plus a short
    cookie TTL is enough."""
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("ascii")


def google_auth_url(client_id: str, redirect_uri: str, state: str) -> str:
    # Keys sorted, as Go's url.Values.Encode() does.
    q = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
    }
    return GOOGLE_AUTH_URL + "?" + urlencode(sorted(q.items()))


def exchange_google_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> str:
    """Exchange an authorization code for an access token."""
    try:
        resp = httpx.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=_TIMEOUT,
        )
        body = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise GoogleError(str(e)) from e

    access_token = body.get("access_token", "") if isinstance(body, dict) else ""
    if resp.status_code != 200 or not access_token:
        err = body.get("error", "") if isinstance(body, dict) else ""
        if err:
            raise GoogleError(f"google token exchange failed: {err}")
        raise GoogleError(f"google token exchange failed: status {resp.status_code}")
    return access_token


def fetch_google_user_info(access_token: str) -> GoogleUserInfo:
    """Fetch the authenticated user's profile using an access token."""
    try:
        resp = httpx.get(GOOGLE_USERINFO_URL, headers={"Authorization": "Bearer " + access_token}, timeout=_TIMEOUT)
    except httpx.HTTPError as e:
        raise GoogleError(str(e)) from e
    if resp.status_code != 200:
        raise GoogleError("google userinfo request failed")
    try:
        body = resp.json()
    except ValueError as e:
        raise GoogleError(str(e)) from e
    info = GoogleUserInfo(
        sub=body.get("sub", "") or "",
        email=body.get("email", "") or "",
        email_verified=body.get("email_verified") is True,
    )
    if not info.sub:
        raise GoogleError("google userinfo response missing sub")
    return info
