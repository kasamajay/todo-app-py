"""Ports of todo-app handlers/auth_handler_test.go and auth_twofactor_test.go."""

from datetime import timedelta

from app.jsonfmt import now
from app.routers.auth import issue_two_factor_challenge


def login(ctx, email, password):
    return ctx.client.post("/api/auth/login", json={"email": email, "password": password})


def test_login_rejects_google_only_account_password_attempt(ctx):
    ctx.seed_user("google-only@example.com", google_id="google-sub-123")
    r = login(ctx, "google-only@example.com", "whatever123")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_credentials"


def test_login_two_factor_enabled_returns_challenge_not_token(ctx):
    user = ctx.seed_user("2fa@example.com", "password123", two_factor=True)
    r = login(ctx, "2fa@example.com", "password123")
    assert r.status_code == 200
    body = r.json()
    assert body == {"two_factor_required": True, "user_id": user.id}
    stored = ctx.state.users.get(user.id)
    assert len(stored.two_factor_code) == 6 and stored.two_factor_code.isdigit()
    assert stored.two_factor_code_expires > now()


def test_login_two_factor_disabled_returns_token_directly(ctx):
    ctx.seed_user("plain@example.com", "password123")
    r = login(ctx, "plain@example.com", "password123")
    assert r.status_code == 200
    assert r.json()["token"]


def verify(ctx, user_id, code):
    return ctx.client.post("/api/auth/2fa/verify", json={"user_id": user_id, "code": code})


def test_verify_two_factor_correct_code(ctx):
    user = issue_two_factor_challenge(ctx.state, ctx.seed_user("a@example.com", "password123", two_factor=True))
    r = verify(ctx, user.id, user.two_factor_code)
    assert r.status_code == 200
    assert r.json()["token"]
    final = ctx.state.users.get(user.id)
    assert final.two_factor_code == "" and final.two_factor_attempts == 0


def test_verify_two_factor_wrong_code_increments_attempts(ctx):
    user = issue_two_factor_challenge(ctx.state, ctx.seed_user("a@example.com", "password123", two_factor=True))
    wrong = "000000" if user.two_factor_code != "000000" else "111111"
    r = verify(ctx, user.id, wrong)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "two_factor_code_incorrect"
    assert ctx.state.users.get(user.id).two_factor_attempts == 1


def test_verify_two_factor_too_many_attempts_invalidates_code(ctx):
    user = issue_two_factor_challenge(ctx.state, ctx.seed_user("a@example.com", "password123", two_factor=True))
    wrong = "000000" if user.two_factor_code != "000000" else "111111"
    for _ in range(4):
        assert verify(ctx, user.id, wrong).json()["error"]["code"] == "two_factor_code_incorrect"
    r = verify(ctx, user.id, wrong)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "two_factor_too_many_attempts"
    final = ctx.state.users.get(user.id)
    assert final.two_factor_code == "" and final.two_factor_attempts == 0
    # Even the right code no longer works: the challenge is gone.
    assert verify(ctx, user.id, user.two_factor_code).json()["error"]["code"] == "two_factor_not_pending"


def test_verify_two_factor_expired_code(ctx):
    user = ctx.seed_user(
        "a@example.com", "password123", two_factor=True,
        two_factor_code="123456", two_factor_code_expires=now() - timedelta(minutes=1),
    )
    r = verify(ctx, user.id, "123456")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "two_factor_code_expired"
    assert ctx.state.users.get(user.id).two_factor_code == ""


def test_verify_two_factor_no_pending_challenge(ctx):
    user = ctx.seed_user("a@example.com", "password123", two_factor=True)
    for uid in (user.id, "does-not-exist"):
        r = verify(ctx, uid, "123456")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "two_factor_not_pending"


def test_update_two_factor_requires_bearer_auth(ctx):
    r = ctx.client.put("/api/auth/2fa", json={"enabled": True})
    assert r.status_code == 401


def test_update_two_factor_toggles_flag(ctx):
    user = ctx.seed_user("a@example.com", "password123")
    r = ctx.client.put("/api/auth/2fa", json={"enabled": True}, headers=ctx.auth(user))
    assert r.status_code == 200 and r.json()["two_factor_enabled"] is True
    assert ctx.state.users.get(user.id).two_factor_enabled is True

    # Disabling also clears any pending challenge.
    issue_two_factor_challenge(ctx.state, ctx.state.users.get(user.id))
    r = ctx.client.put("/api/auth/2fa", json={"enabled": False}, headers=ctx.auth(user))
    assert r.status_code == 200 and r.json()["two_factor_enabled"] is False
    assert ctx.state.users.get(user.id).two_factor_code == ""
