"""Ports of todo-app handlers/tasks_handler_test.go, plus task CRUD and
due-date behaviour."""

from datetime import datetime, timezone

import pytest

from app.routers.tasks import parse_due_date


@pytest.mark.parametrize(
    "raw,want",
    [
        ("", None),
        ("   ", None),
        ("2026-10-01T00:00:00Z", datetime(2026, 10, 1, tzinfo=timezone.utc)),
        ("2026-10-01T12:30:45.123456789Z", datetime(2026, 10, 1, 12, 30, 45, 123456, tzinfo=timezone.utc)),
    ],
)
def test_parse_due_date_valid(raw, want):
    assert parse_due_date(raw) == want


@pytest.mark.parametrize("raw", ["2026-10-01", "not-a-date", "2026-13-01T00:00:00Z", "2026-10-01 00:00:00Z"])
def test_parse_due_date_invalid(raw):
    with pytest.raises(ValueError):
        parse_due_date(raw)


@pytest.fixture
def setup(ctx):
    alice = ctx.seed_user("alice@example.com")
    board = ctx.seed_board(alice)
    return ctx, alice, board


def create(ctx, user, **body):
    return ctx.client.post("/api/tasks", json=body, headers=ctx.auth(user))


def test_tasks_create_accepts_valid_label_ids(setup):
    ctx, alice, board = setup
    l1, l2 = ctx.seed_label(alice, board), ctx.seed_label(alice, board, "Two")
    r = create(ctx, alice, board_id=board.id, title="T", label_ids=[l1.id, l2.id])
    assert r.status_code == 201
    assert r.json()["label_ids"] == [l1.id, l2.id]


def test_tasks_create_rejects_label_from_another_board(setup):
    ctx, alice, board = setup
    other_label = ctx.seed_label(alice, ctx.seed_board(alice, "Other"))
    r = create(ctx, alice, board_id=board.id, title="T", label_ids=[other_label.id])
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_label"


def test_tasks_create_rejects_label_from_another_user(setup):
    ctx, alice, board = setup
    bob = ctx.seed_user("bob@example.com")
    bobs_label = ctx.seed_label(bob, board)  # same board id, wrong owner
    r = create(ctx, alice, board_id=board.id, title="T", label_ids=[bobs_label.id])
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_label"


def test_tasks_create_rejects_unknown_label_id(setup):
    ctx, alice, board = setup
    r = create(ctx, alice, board_id=board.id, title="T", label_ids=["nope"])
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_label"


def test_tasks_create_omitted_label_ids_defaults_empty(setup):
    ctx, alice, board = setup
    r = create(ctx, alice, board_id=board.id, title="T")
    assert r.status_code == 201
    body = r.json()
    # omitempty: an empty label list and a nil due date are left out entirely.
    assert "label_ids" not in body and "due_date" not in body
    assert body["status"] == "todo" and body["description"] == ""
    assert ctx.state.tasks.get(body["id"]).label_ids == []


def test_tasks_update_replaces_label_ids(setup):
    ctx, alice, board = setup
    l1, l2 = ctx.seed_label(alice, board), ctx.seed_label(alice, board, "Two")
    task = ctx.seed_task(alice, board, label_ids=[l1.id])
    r = ctx.client.put(f"/api/tasks/{task.id}", json={"label_ids": [l2.id]}, headers=ctx.auth(alice))
    assert r.status_code == 200 and r.json()["label_ids"] == [l2.id]


def test_tasks_update_empty_array_clears_labels(setup):
    ctx, alice, board = setup
    l1 = ctx.seed_label(alice, board)
    task = ctx.seed_task(alice, board, label_ids=[l1.id])
    r = ctx.client.put(f"/api/tasks/{task.id}", json={"label_ids": []}, headers=ctx.auth(alice))
    assert r.status_code == 200 and "label_ids" not in r.json()
    assert ctx.state.tasks.get(task.id).label_ids == []


def test_tasks_update_omitted_label_ids_leaves_unchanged(setup):
    ctx, alice, board = setup
    l1 = ctx.seed_label(alice, board)
    task = ctx.seed_task(alice, board, label_ids=[l1.id])
    r = ctx.client.put(f"/api/tasks/{task.id}", json={"title": "New"}, headers=ctx.auth(alice))
    assert r.status_code == 200 and r.json()["label_ids"] == [l1.id] and r.json()["title"] == "New"


def test_tasks_update_rejects_invalid_label_id_no_partial_apply(setup):
    ctx, alice, board = setup
    task = ctx.seed_task(alice, board, title="Original")
    r = ctx.client.put(
        f"/api/tasks/{task.id}", json={"title": "Changed", "label_ids": ["bogus"]}, headers=ctx.auth(alice)
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_label"
    stored = ctx.state.tasks.get(task.id)
    assert stored.title == "Original" and stored.updated_at == task.updated_at


def test_task_status_due_date_and_board_rules(setup):
    ctx, alice, board = setup
    bob = ctx.seed_user("bob@example.com")
    assert create(ctx, alice, board_id=board.id).json()["error"]["code"] == "invalid_title"
    assert create(ctx, alice, board_id=board.id, title=" ").json()["error"]["code"] == "invalid_title"
    assert create(ctx, alice, board_id="missing", title="T").json()["error"]["code"] == "invalid_board"
    assert create(ctx, bob, board_id=board.id, title="T").json()["error"]["code"] == "invalid_board"
    assert create(ctx, alice, board_id=board.id, title="T", status="blocked").json()["error"]["code"] == "invalid_status"
    assert create(ctx, alice, board_id=board.id, title="T", due_date="2026-10-01").json()["error"]["code"] == "invalid_due_date"

    r = create(ctx, alice, board_id=board.id, title="T", status="in_progress", due_date="2026-10-01T00:00:00Z")
    assert r.status_code == 201
    task = r.json()
    assert task["status"] == "in_progress" and task["due_date"] == "2026-10-01T00:00:00Z"

    # "" clears the due date; absent/null leaves it alone.
    r = ctx.client.put(f"/api/tasks/{task['id']}", json={"due_date": None, "status": "done"}, headers=ctx.auth(alice))
    assert r.json()["due_date"] == "2026-10-01T00:00:00Z" and r.json()["status"] == "done"
    r = ctx.client.put(f"/api/tasks/{task['id']}", json={"due_date": ""}, headers=ctx.auth(alice))
    assert "due_date" not in r.json()
    assert ctx.client.put(f"/api/tasks/{task['id']}", json={"title": ""}, headers=ctx.auth(alice)).json()["error"]["code"] == "invalid_title"

    # Ownership: 404 for someone else's task.
    assert ctx.client.put(f"/api/tasks/{task['id']}", json={}, headers=ctx.auth(bob)).status_code == 404
    assert ctx.client.delete(f"/api/tasks/{task['id']}", headers=ctx.auth(bob)).status_code == 404


def test_tasks_list_filters_by_board_and_owner(setup):
    ctx, alice, board = setup
    other = ctx.seed_board(alice, "Other")
    t1, t2 = ctx.seed_task(alice, board), ctx.seed_task(alice, other)
    bob = ctx.seed_user("bob@example.com")
    ctx.seed_task(bob, ctx.seed_board(bob))

    all_ids = {t["id"] for t in ctx.client.get("/api/tasks", headers=ctx.auth(alice)).json()}
    assert all_ids == {t1.id, t2.id}
    assert [t["id"] for t in ctx.client.get(f"/api/tasks?board_id={board.id}", headers=ctx.auth(alice)).json()] == [t1.id]
    # Someone else's board id just yields an empty list (no 404), as in Go.
    assert ctx.client.get(f"/api/tasks?board_id={board.id}", headers=ctx.auth(bob)).json() == []


def test_task_board_reassignment(setup):
    ctx, alice, board = setup
    other = ctx.seed_board(alice, "Other")
    task = ctx.seed_task(alice, board)
    r = ctx.client.put(f"/api/tasks/{task.id}", json={"board_id": other.id}, headers=ctx.auth(alice))
    assert r.status_code == 200 and r.json()["board_id"] == other.id
    r = ctx.client.put(f"/api/tasks/{task.id}", json={"board_id": "missing"}, headers=ctx.auth(alice))
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_board"
