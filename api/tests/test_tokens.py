"""Ports of todo-app api/internal/auth/token_test.go, plus cross-backend
format checks."""

import base64
import hashlib
import hmac
import json
from datetime import timedelta

import pytest

from app.auth import tokens
from app.jsonfmt import now


def claims(uid="u1", admin=False, delta=timedelta(hours=1)):
    return tokens.Claims(uid, admin, now() + delta)


def test_mint_and_verify_round_trip():
    secret = b"test-secret-32-bytes-long-------"
    token = tokens.mint(secret, claims())
    assert "." in token
    got = tokens.verify(secret, token)
    assert (got.user_id, got.is_admin) == ("u1", False)


def test_verify_rejects_tampered_signature():
    token = tokens.mint(b"secret", claims())
    tampered = token.split(".", 1)[0] + "." + "0" * 64
    with pytest.raises(tokens.InvalidToken):
        tokens.verify(b"secret", tampered)


def test_verify_rejects_wrong_secret():
    token = tokens.mint(b"secret-a", claims())
    with pytest.raises(tokens.InvalidToken):
        tokens.verify(b"secret-b", token)


def test_verify_rejects_expired_token():
    token = tokens.mint(b"secret", claims(delta=-timedelta(minutes=1)))
    with pytest.raises(tokens.ExpiredToken):
        tokens.verify(b"secret", token)


@pytest.mark.parametrize("tok", ["", "no-dot-here", ".", "abc.", ".def"])
def test_verify_rejects_malformed_token(tok):
    with pytest.raises(tokens.MalformedToken):
        tokens.verify(b"secret", tok)


def test_token_format_matches_go():
    token = tokens.mint(b"secret", claims("abc", True))
    encoded, sig = token.split(".")
    assert "=" not in encoded
    payload = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert list(payload) == ["uid", "adm", "exp"]
    assert payload["uid"] == "abc" and payload["adm"] is True and payload["exp"].endswith("Z")
    assert sig == hmac.new(b"secret", encoded.encode(), hashlib.sha256).hexdigest()


def test_verifies_a_token_minted_by_the_go_backend():
    # Built exactly as Go's auth.Mint does, with a nanosecond-precision exp.
    payload = b'{"uid":"go-user","adm":false,"exp":"2999-01-02T03:04:05.123456789Z"}'
    encoded = base64.urlsafe_b64encode(payload).rstrip(b"=").decode()
    token = encoded + "." + hmac.new(b"k", encoded.encode(), hashlib.sha256).hexdigest()
    got = tokens.verify(b"k", token)
    assert got.user_id == "go-user" and got.is_admin is False
