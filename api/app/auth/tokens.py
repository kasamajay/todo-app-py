"""Custom HMAC-SHA256 API tokens (not JWT), format-compatible with the Go API:

    base64url_nopad(json {"uid","adm","exp"}) + "." + hex(HMAC-SHA256(secret, first part))

Tokens are self-contained and stateless - there is no server-side session
store, so "logout" is a client-side token discard (decisions/0003). A token
minted by either backend verifies in the other given the same secret.key."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..jsonfmt import format_time, now, parse_time

TOKEN_TTL = timedelta(hours=24)

_B64URL_RE = re.compile(r"^[A-Za-z0-9_-]*$")


class TokenError(Exception):
    pass


class MalformedToken(TokenError):
    pass


class InvalidToken(TokenError):
    pass


class ExpiredToken(TokenError):
    pass


@dataclass
class Claims:
    user_id: str
    is_admin: bool
    expires_at: datetime


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    # Mirror Go's base64.RawURLEncoding: no padding, URL alphabet only.
    if not _B64URL_RE.match(s) or len(s) % 4 == 1:
        raise MalformedToken("malformed token")
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(secret: bytes, encoded_payload: str) -> str:
    return hmac.new(secret, encoded_payload.encode("ascii"), hashlib.sha256).hexdigest()


def mint(secret: bytes, claims: Claims) -> str:
    payload = json.dumps(
        {"uid": claims.user_id, "adm": claims.is_admin, "exp": format_time(claims.expires_at)},
        separators=(",", ":"),
    ).encode("utf-8")
    encoded = _b64url_encode(payload)
    return encoded + "." + _sign(secret, encoded)


def verify(secret: bytes, token: str) -> Claims:
    """Check the token's signature and expiry, returning its Claims."""
    parts = token.split(".", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise MalformedToken("malformed token")
    encoded, provided_sig = parts

    if not hmac.compare_digest(_sign(secret, encoded).encode(), provided_sig.encode()):
        raise InvalidToken("invalid token signature")

    try:
        c = json.loads(_b64url_decode(encoded))
        claims = Claims(
            user_id=c.get("uid", ""),
            is_admin=bool(c.get("adm", False)),
            expires_at=parse_time(c.get("exp", "")),
        )
    except (ValueError, TypeError, AttributeError) as e:
        raise MalformedToken("malformed token") from e

    if now() > claims.expires_at:
        raise ExpiredToken("token expired")
    return claims
