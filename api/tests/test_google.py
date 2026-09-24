"""Ports of todo-app auth/google_test.go and handlers/auth_google_handler_test.go."""

from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

from app.auth.google import GOOGLE_AUTH_URL, google_auth_url, random_state
from tests.conftest import REDIRECT_URI


def test_random_state_non_empty_and_distinct():
    a, b = random_state(), random_state()
    assert a and b and a != b


def test_google_auth_url():
    u = urlparse(google_auth_url("client-123", REDIRECT_URI, "state-abc"))
    assert f"{u.scheme}://{u.netloc}{u.path}" == GOOGLE_AUTH_URL
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert q["client_id"] == "client-123"
    assert q["redirect_uri"] == REDIRECT_URI
    assert q["response_type"] == "code"
    assert q["state"] == "state-abc"
    assert "openid" in q["scope"] and "email" in q["scope"]


def test_google_login_not_configured(ctx):
    r = ctx.client.get("/api/auth/google/login")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "google_oauth_not_configured"


def test_google_login_redirects_to_google_with_state_cookie(gctx):
    r = gctx.client.get("/api/auth/google/login")
    assert r.status_code == 302
    loc = urlparse(r.headers["location"])
    assert loc.netloc == "accounts.google.com"
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    assert q["client_id"] == "test-client-id"
    assert q["redirect_uri"] == REDIRECT_URI
    assert q["response_type"] == "code"
    assert q["state"]

    cookie = SimpleCookie(r.headers["set-cookie"])["google_oauth_state"]
    assert cookie.value == q["state"]
    assert cookie["httponly"]
    # Same attributes as the Go handler's http.Cookie.
    assert cookie["path"] == "/api/auth/google"
    assert cookie["max-age"] == "300"
    assert cookie["samesite"].lower() == "lax"


def assert_redirects_with_google_error(r, want_code):
    assert r.status_code == 302
    frag = parse_qs(urlparse(r.headers["location"]).fragment)
    assert frag["google_error"] == [want_code]


def test_google_callback_missing_state_cookie(gctx):
    r = gctx.client.get("/api/auth/google/callback?code=abc&state=xyz")
    assert_redirects_with_google_error(r, "google_state_missing")


def test_google_callback_state_mismatch(gctx):
    gctx.client.cookies.set("google_oauth_state", "correct-value")
    r = gctx.client.get("/api/auth/google/callback?code=abc&state=wrong-value")
    assert_redirects_with_google_error(r, "google_state_mismatch")
    # One-time use: the state cookie is cleared even on failure.
    assert "google_oauth_state=" in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]


def test_google_callback_user_denied(gctx):
    r = gctx.client.get("/api/auth/google/callback?error=access_denied")
    assert_redirects_with_google_error(r, "google_denied")
    assert r.headers["location"].startswith("http://localhost:5173/#google_error=")


def test_google_callback_not_configured(ctx):
    r = ctx.client.get("/api/auth/google/callback?code=abc&state=xyz")
    assert_redirects_with_google_error(r, "google_oauth_not_configured")
