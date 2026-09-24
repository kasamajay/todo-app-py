"""Ports of todo-app handlers/labels_handler_test.go."""

import pytest


@pytest.fixture
def setup(ctx):
    alice = ctx.seed_user("alice@example.com")
    bob = ctx.seed_user("bob@example.com")
    board = ctx.seed_board(alice)
    return ctx, alice, bob, board


def err(r):
    return r.json()["error"]["code"]


def test_labels_list_requires_board_id(setup):
    ctx, alice, _, _ = setup
    r = ctx.client.get("/api/labels", headers=ctx.auth(alice))
    assert r.status_code == 400 and err(r) == "invalid_board"
    assert r.json()["error"]["message"] == "board_id is required"


def test_labels_list_rejects_board_not_owned_by_caller(setup):
    ctx, _, bob, board = setup
    r = ctx.client.get(f"/api/labels?board_id={board.id}", headers=ctx.auth(bob))
    assert r.status_code == 400 and err(r) == "invalid_board"


def test_labels_list_returns_only_that_boards_labels(setup):
    ctx, alice, _, board = setup
    other = ctx.seed_board(alice, "Other")
    mine = ctx.seed_label(alice, board)
    ctx.seed_label(alice, other)
    r = ctx.client.get(f"/api/labels?board_id={board.id}", headers=ctx.auth(alice))
    assert r.status_code == 200
    assert [l["id"] for l in r.json()] == [mine.id]


def test_labels_create_success(setup):
    ctx, alice, _, board = setup
    r = ctx.client.post("/api/labels", json={"board_id": board.id, "name": "Bug", "color": "#ef4444"}, headers=ctx.auth(alice))
    assert r.status_code == 201
    body = r.json()
    assert list(body) == ["id", "user_id", "board_id", "name", "color", "created_at"]
    assert (body["user_id"], body["board_id"], body["name"], body["color"]) == (alice.id, board.id, "Bug", "#ef4444")
    assert ctx.state.labels.get(body["id"]) is not None


def test_labels_create_rejects_empty_name(setup):
    ctx, alice, _, board = setup
    r = ctx.client.post("/api/labels", json={"board_id": board.id, "name": " ", "color": "#ef4444"}, headers=ctx.auth(alice))
    assert r.status_code == 400 and err(r) == "invalid_name"


def test_labels_create_rejects_invalid_color(setup):
    ctx, alice, _, board = setup
    r = ctx.client.post("/api/labels", json={"board_id": board.id, "name": "Bug", "color": "#123456"}, headers=ctx.auth(alice))
    assert r.status_code == 400 and err(r) == "invalid_color"


def test_labels_create_rejects_board_not_owned(setup):
    ctx, _, bob, board = setup
    r = ctx.client.post("/api/labels", json={"board_id": board.id, "name": "Bug", "color": "#ef4444"}, headers=ctx.auth(bob))
    assert r.status_code == 400 and err(r) == "invalid_board"


def test_labels_update_success(setup):
    ctx, alice, _, board = setup
    label = ctx.seed_label(alice, board)
    r = ctx.client.put(f"/api/labels/{label.id}", json={"name": "Renamed", "color": "#16a34a"}, headers=ctx.auth(alice))
    assert r.status_code == 200
    assert (r.json()["name"], r.json()["color"]) == ("Renamed", "#16a34a")
    stored = ctx.state.labels.get(label.id)
    assert (stored.name, stored.color) == ("Renamed", "#16a34a")


def test_labels_update_not_found_or_not_owned(setup):
    ctx, alice, bob, board = setup
    label = ctx.seed_label(alice, board)
    for who, lid in ((bob, label.id), (alice, "missing")):
        r = ctx.client.put(f"/api/labels/{lid}", json={"name": "x", "color": "#16a34a"}, headers=ctx.auth(who))
        assert r.status_code == 404 and err(r) == "not_found"


def test_labels_update_rejects_invalid_color(setup):
    ctx, alice, _, board = setup
    label = ctx.seed_label(alice, board)
    r = ctx.client.put(f"/api/labels/{label.id}", json={"name": "x", "color": "red"}, headers=ctx.auth(alice))
    assert r.status_code == 400 and err(r) == "invalid_color"
    assert ctx.state.labels.get(label.id).color == "#6366f1"


def test_labels_delete_success_strips_from_referencing_tasks(setup):
    ctx, alice, _, board = setup
    doomed = ctx.seed_label(alice, board)
    keep = ctx.seed_label(alice, board, "Keep")
    t1 = ctx.seed_task(alice, board, label_ids=[doomed.id, keep.id])
    t2 = ctx.seed_task(alice, board, label_ids=[doomed.id])
    t3 = ctx.seed_task(alice, board)

    r = ctx.client.delete(f"/api/labels/{doomed.id}", headers=ctx.auth(alice))
    assert r.status_code == 204
    assert ctx.state.labels.get(doomed.id) is None
    assert ctx.state.tasks.get(t1.id).label_ids == [keep.id]
    assert ctx.state.tasks.get(t2.id).label_ids == []
    assert ctx.state.tasks.get(t3.id) is not None  # tasks themselves survive


def test_labels_delete_not_found_or_not_owned(setup):
    ctx, alice, bob, board = setup
    label = ctx.seed_label(alice, board)
    for who, lid in ((bob, label.id), (alice, "missing")):
        r = ctx.client.delete(f"/api/labels/{lid}", headers=ctx.auth(who))
        assert r.status_code == 404 and err(r) == "not_found"
    assert ctx.state.labels.get(label.id) is not None


def test_labels_delete_leaves_other_boards_tasks_untouched(setup):
    ctx, alice, _, board = setup
    other = ctx.seed_board(alice, "Other")
    label = ctx.seed_label(alice, board)
    other_task = ctx.seed_task(alice, other, label_ids=[label.id])  # not reachable via UI, but must be left alone
    before = ctx.state.tasks.get(other_task.id)

    assert ctx.client.delete(f"/api/labels/{label.id}", headers=ctx.auth(alice)).status_code == 204
    after = ctx.state.tasks.get(other_task.id)
    assert after.label_ids == [label.id] and after.updated_at == before.updated_at


def test_labels_require_auth(ctx):
    assert ctx.client.get("/api/labels?board_id=x").status_code == 401
