"""Contract-parity tests: behaviour and wire details the Go API has that the
unchanged React frontend (or a shared data directory) relies on."""

import base64
import json
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from app.auth import google, passwords
from app.jsonfmt import format_time, now, parse_time
from tests.conftest import Ctx

# --- JSON formatting -------------------------------------------------------


def test_time_format_matches_go_rfc3339nano():
    assert format_time(parse_time("0001-01-01T00:00:00Z")) == "0001-01-01T00:00:00Z"
    assert format_time(parse_time("2026-09-24T13:00:42.338551558Z")) == "2026-09-24T13:00:42.338551Z"
    assert format_time(parse_time("2026-09-24T13:00:42.500000Z")) == "2026-09-24T13:00:42.5Z"
    assert format_time(parse_time("2026-09-24T13:00:42+05:30")) == "2026-09-24T13:00:42+05:30"


def test_public_user_shape_and_zero_time(ctx):
    r = ctx.client.post("/api/auth/register", json={"email": " New@Example.com ", "password": "password123"})
    assert r.status_code == 201
    body = r.json()
    assert list(body) == ["token", "user"]
    user = body["user"]
    assert list(user) == ["id", "email", "is_admin", "failed_login_count", "locked_until", "two_factor_enabled", "created_at"]
    assert user["email"] == "new@example.com"  # trimmed + lower-cased
    # Go's omitempty never drops a time.Time: the zero value is emitted.
    assert user["locked_until"] == "0001-01-01T00:00:00Z"
    assert r.headers["content-type"] == "application/json"


# --- request decoding / routing -------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [b"", b"not json", b"[]", b'"str"', b'{"email":"a@b.c","password":"password123","extra":1}',
     b'{"email":5,"password":"password123"}'],
)
def test_strict_body_decoding(ctx, raw):
    r = ctx.client.post("/api/auth/register", content=raw, headers={"content-type": "application/json"})
    assert r.status_code == 400
    assert r.json() == {"error": {"code": "invalid_body", "message": "request body must be valid JSON"}}


def test_body_decoding_go_leniencies(ctx):
    # null body -> no fields; case-insensitive keys; trailing data ignored.
    assert ctx.client.post("/api/auth/register", content=b"null").json()["error"]["code"] == "invalid_email"
    r = ctx.client.post("/api/auth/register", content=b'{"EMAIL":"x@y.z","Password":"password123"} trailing')
    assert r.status_code == 201


def test_unknown_routes_and_methods_match_go_servemux(ctx):
    r = ctx.client.get("/api/nope")
    assert r.status_code == 404 and r.text == "404 page not found\n"
    assert ctx.client.get("/api/boards/").status_code == 404  # no trailing-slash redirect
    r = ctx.client.patch("/api/boards")
    assert r.status_code == 405 and r.text == "Method Not Allowed\n"
    assert ctx.client.get("/docs").status_code == 404
    assert ctx.client.get("/openapi.json").status_code == 404


def test_auth_failures(ctx):
    admin_only = ("get", "/api/admin/users")
    for method, path in (("get", "/api/auth/me"), ("get", "/api/boards"), ("post", "/api/auth/logout"), admin_only):
        r = getattr(ctx.client, method)(path)
        assert r.status_code == 401
        assert r.json() == {"error": {"code": "unauthorized", "message": "missing or invalid token"}}
    for header in ("Bearer nope", "Basic abc", "bearer x"):
        assert ctx.client.get("/api/auth/me", headers={"Authorization": header}).status_code == 401
    user = ctx.seed_user("a@example.com")
    r = ctx.client.get("/api/admin/users", headers=ctx.auth(user))
    assert r.status_code == 403
    assert r.json() == {"error": {"code": "forbidden", "message": "admin access required"}}
    assert ctx.client.post("/api/auth/logout", headers=ctx.auth(user)).status_code == 204


# --- auth flows --------------------------------------------------------------


def test_register_validation(ctx):
    post = lambda body: ctx.client.post("/api/auth/register", json=body).json()["error"]["code"]
    assert post({"email": "nope", "password": "password123"}) == "invalid_email"
    assert post({"email": "a@b.c", "password": "short"}) == "invalid_password"
    ctx.seed_user("taken@example.com", "password123")
    r = ctx.client.post("/api/auth/register", json={"email": "TAKEN@example.com", "password": "password123"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "email_taken"


def test_login_lockout_and_admin_unlock(ctx):
    user = ctx.seed_user("a@example.com", "password123")
    admin = ctx.seed_user("root@example.com", "adminpass1", is_admin=True)
    login = lambda pw: ctx.client.post("/api/auth/login", json={"email": "a@example.com", "password": pw})

    assert login("wrong-1").status_code == 401
    assert login("wrong-2").status_code == 401
    r = login("wrong-3")
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"
    stored = ctx.state.users.get(user.id)
    assert stored.failed_login_count == 3 and stored.locked_until > now() + timedelta(minutes=29)

    r = login("password123")  # right password, still locked
    assert r.status_code == 403 and r.json()["error"]["code"] == "account_locked"

    users = ctx.client.get("/api/admin/users", headers=ctx.auth(admin)).json()
    locked = next(u for u in users if u["id"] == user.id)
    assert locked["failed_login_count"] == 3 and locked["locked_until"] != "0001-01-01T00:00:00Z"

    r = ctx.client.post(f"/api/admin/users/{user.id}/unlock", headers=ctx.auth(admin))
    assert r.status_code == 200 and r.json()["locked_until"] == "0001-01-01T00:00:00Z"
    assert ctx.client.post("/api/admin/users/missing/unlock", headers=ctx.auth(admin)).status_code == 404
    assert login("password123").status_code == 200


def test_unknown_email_login_is_401(ctx):
    r = ctx.client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "password123"})
    assert r.status_code == 401 and r.json()["error"]["code"] == "invalid_credentials"


def test_forgot_and_reset_password(ctx):
    user = ctx.seed_user("a@example.com", "oldpassword")
    msg = {"message": "if that email exists, a reset link has been sent"}
    assert ctx.client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"}).json() == msg
    r = ctx.client.post("/api/auth/forgot-password", json={"email": "A@example.com"})
    assert r.status_code == 200 and r.json() == msg

    token = ctx.state.users.get(user.id).reset_token
    assert len(token) == 32
    reset = lambda body: ctx.client.post("/api/auth/reset-password", json=body)
    assert reset({"token": token, "new_password": "short"}).json()["error"]["code"] == "invalid_password"
    assert reset({"token": "bogus", "new_password": "newpassword"}).json()["error"]["code"] == "invalid_token"
    r = reset({"token": token, "new_password": "newpassword"})
    assert r.status_code == 200 and r.json() == {"message": "password has been reset"}
    assert reset({"token": token, "new_password": "newpassword"}).json()["error"]["code"] == "invalid_token"
    assert ctx.client.post("/api/auth/login", json={"email": "a@example.com", "password": "newpassword"}).status_code == 200


def test_bootstrap_admin_created_once(tmp_path):
    first = Ctx(tmp_path)
    users = first.state.users.list()
    assert [(u.email, u.is_admin) for u in users] == [("admin@todo.io", True)]
    second = Ctx(tmp_path)  # restart against the same data dir
    assert [u.id for u in second.state.users.list()] == [users[0].id]
    assert (tmp_path / "secret.key").read_bytes() == second.state.secret


# --- Google OAuth callback paths (Google itself stubbed) -------------------


@pytest.fixture
def google_ok(monkeypatch):
    profile = {"sub": "g-123", "email": "Person@Gmail.com", "email_verified": True}
    monkeypatch.setattr(google, "exchange_google_code", lambda *a: "access-token")
    monkeypatch.setattr(google, "fetch_google_user_info", lambda tok: google.GoogleUserInfo(**profile))
    return profile


def callback(gctx):
    gctx.client.cookies.set("google_oauth_state", "st")
    return gctx.client.get("/api/auth/google/callback?code=abc&state=st")


def fragment(r):
    assert r.status_code == 302
    return {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).fragment).items()}


def test_google_callback_creates_account_and_returns_token(gctx, google_ok):
    frag = fragment(callback(gctx))
    token = frag["google_token"]
    me = gctx.client.get("/api/auth/me", headers={"Authorization": "Bearer " + token}).json()
    assert me["email"] == "person@gmail.com"
    stored = gctx.state.users.find_by_email("person@gmail.com")
    assert stored.google_id == "g-123" and stored.password_hash is None


def test_google_callback_auto_links_existing_email(gctx, google_ok):
    existing = gctx.seed_user("person@gmail.com", "password123")
    assert "google_token" in fragment(callback(gctx))
    assert gctx.state.users.get(existing.id).google_id == "g-123"
    assert len(gctx.state.users.list()) == 2  # bootstrap admin + the linked account


def test_google_callback_two_factor_and_lock(gctx, google_ok):
    user = gctx.seed_user("person@gmail.com", google_id="g-123", two_factor=True)
    assert fragment(callback(gctx)) == {"google_2fa_required": user.id}
    locked = gctx.state.users.get(user.id)
    locked.locked_until = now() + timedelta(minutes=5)
    gctx.state.users.put(locked.id, locked)
    assert fragment(callback(gctx)) == {"google_error": "google_account_locked"}


def test_google_callback_failures(gctx, monkeypatch, google_ok):
    monkeypatch.setattr(google, "fetch_google_user_info", lambda tok: google.GoogleUserInfo("g", "x@y.z", False))
    assert fragment(callback(gctx)) == {"google_error": "google_email_unverified"}

    def boom(*a):
        raise google.GoogleError("down")

    monkeypatch.setattr(google, "fetch_google_user_info", boom)
    assert fragment(callback(gctx)) == {"google_error": "google_userinfo_failed"}
    monkeypatch.setattr(google, "exchange_google_code", boom)
    assert fragment(callback(gctx)) == {"google_error": "google_exchange_failed"}
    gctx.client.cookies.set("google_oauth_state", "st")
    r = gctx.client.get("/api/auth/google/callback?state=st")
    assert fragment(r) == {"google_error": "google_missing_code"}


# --- attachments ---------------------------------------------------------------


def test_attachment_round_trip_limits_and_cascade(ctx):
    alice, bob = ctx.seed_user("alice@example.com"), ctx.seed_user("bob@example.com")
    task = ctx.seed_task(alice, ctx.seed_board(alice))
    base = f"/api/tasks/{task.id}/attachments"
    h = ctx.auth(alice)

    r = ctx.client.post(base, files={"file": ("../notes.txt", b"hello world", "text/plain")}, headers=h)
    assert r.status_code == 201
    att = r.json()
    assert list(att) == ["id", "task_id", "user_id", "filename", "content_type", "size_bytes", "created_at"]
    assert (att["filename"], att["content_type"], att["size_bytes"]) == ("notes.txt", "text/plain", 11)

    r = ctx.client.get(f"{base}/{att['id']}", headers=h)
    assert r.status_code == 200 and r.content == b"hello world"
    assert r.headers["content-type"] == "text/plain"  # no charset appended
    assert r.headers["content-disposition"] == 'inline; filename="notes.txt"'
    assert r.headers["content-length"] == "11"
    assert [a["id"] for a in ctx.client.get(base, headers=h).json()] == [att["id"]]

    # Ownership and field checks.
    assert ctx.client.get(base, headers=ctx.auth(bob)).status_code == 404
    assert ctx.client.get(f"{base}/missing", headers=h).json()["error"]["message"] == "attachment not found"
    r = ctx.client.post(base, files={"other": ("a.txt", b"x")}, headers=h)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_file"
    assert ctx.client.post(base, content=b"raw", headers=h).json()["error"]["code"] == "file_too_large"

    # 10MB limit: exactly 10MB is fine, one byte over is 413.
    limit = 10 * 1024 * 1024
    assert ctx.client.post(base, files={"file": ("ok.bin", b"\0" * limit)}, headers=h).status_code == 201
    r = ctx.client.post(base, files={"file": ("big.bin", b"\0" * (limit + 1))}, headers=h)
    assert r.status_code == 413 and r.json()["error"] == {"code": "file_too_large", "message": "attachment exceeds the 10MB limit"}

    # Deleting the task cascades to attachment metadata and blobs.
    blob = ctx.state.attachments.blob_path(att["id"])
    assert ctx.client.delete(f"/api/tasks/{task.id}", headers=h).status_code == 204
    assert ctx.state.attachments.list_by_task(task.id) == []
    import os
    assert not os.path.exists(blob)


def test_attachment_delete(ctx):
    alice = ctx.seed_user("alice@example.com")
    task = ctx.seed_task(alice, ctx.seed_board(alice))
    h = ctx.auth(alice)
    att = ctx.client.post(f"/api/tasks/{task.id}/attachments", files={"file": ("a.png", b"\x89PNG\r\n\x1a\nxx", "")}, headers=h).json()
    assert att["content_type"] == "image/png"  # sniffed when the part has no type
    assert ctx.client.delete(f"/api/tasks/{task.id}/attachments/{att['id']}", headers=h).status_code == 204
    assert ctx.client.get(f"/api/tasks/{task.id}/attachments", headers=h).json() == []


# --- data-directory compatibility with the Go backend ---------------------------


def test_reads_and_serves_go_written_data(tmp_path):
    """users.json / tasks.json exactly as the Go backend writes them
    (nanosecond times, base64 []byte, null hash for a Google-only account,
    omitted empty fields) load, serve, and round-trip."""
    pw_hash, salt = passwords.hash_password("gopassword")
    users = {
        "u1": {
            "id": "u1", "email": "go@example.com",
            "password_hash": base64.b64encode(pw_hash).decode(), "salt": base64.b64encode(salt).decode(),
            "is_admin": True, "failed_login_count": 0, "locked_until": "0001-01-01T00:00:00Z",
            "reset_token_expires": "0001-01-01T00:00:00Z", "two_factor_enabled": False,
            "two_factor_code_expires": "0001-01-01T00:00:00Z", "created_at": "2026-09-22T10:00:00.123456789Z",
        },
        "u2": {
            "id": "u2", "email": "g@example.com", "password_hash": None, "salt": None, "google_id": "sub",
            "is_admin": False, "failed_login_count": 0, "locked_until": "0001-01-01T00:00:00Z",
            "reset_token_expires": "0001-01-01T00:00:00Z", "two_factor_enabled": False,
            "two_factor_code_expires": "0001-01-01T00:00:00Z", "created_at": "2026-09-22T10:00:00Z",
        },
    }
    tasks = {"t1": {"id": "t1", "user_id": "u1", "board_id": "b1", "title": "Go task", "description": "",
                    "status": "done", "due_date": "2026-10-01T00:00:00Z",
                    "created_at": "2026-09-22T10:00:00.5Z", "updated_at": "2026-09-22T10:00:00.5Z"}}
    (tmp_path / "users.json").write_text(json.dumps(users, indent=2))
    (tmp_path / "tasks.json").write_text(json.dumps(tasks, indent=2))

    ctx = Ctx(tmp_path)
    assert len(ctx.state.users.list()) == 2  # no bootstrap admin: users exist
    r = ctx.client.post("/api/auth/login", json={"email": "go@example.com", "password": "gopassword"})
    assert r.status_code == 200
    token = r.json()["token"]
    got = ctx.client.get("/api/tasks", headers={"Authorization": "Bearer " + token}).json()
    assert got == [{"id": "t1", "user_id": "u1", "board_id": "b1", "title": "Go task", "description": "",
                    "status": "done", "due_date": "2026-10-01T00:00:00Z",
                    "created_at": "2026-09-22T10:00:00.5Z", "updated_at": "2026-09-22T10:00:00.5Z"}]
    assert ctx.client.post("/api/auth/login", json={"email": "g@example.com", "password": "x" * 8}).status_code == 401

    # Rewritten file keeps Go's shape: null hash, omitted empty strings, sorted ids.
    ctx.state.users.put("u2", ctx.state.users.get("u2"))
    written = json.loads((tmp_path / "users.json").read_text())
    assert list(written) == ["u1", "u2"]
    assert written["u2"]["password_hash"] is None and "reset_token" not in written["u2"]
    assert written["u2"]["google_id"] == "sub"
