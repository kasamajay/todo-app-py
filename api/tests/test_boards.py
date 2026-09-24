"""Ports of todo-app handlers/boards_handler_test.go, plus board CRUD."""


def test_boards_delete_cascades_to_labels(ctx):
    user = ctx.seed_user("a@example.com")
    board = ctx.seed_board(user)
    other = ctx.seed_board(user, "Other")
    l1 = ctx.seed_label(user, board)
    l2 = ctx.seed_label(user, board, "Second")
    keep = ctx.seed_label(user, other)
    task = ctx.seed_task(user, board, label_ids=[l1.id])

    r = ctx.client.delete(f"/api/boards/{board.id}", headers=ctx.auth(user))
    assert r.status_code == 204
    assert r.content == b""
    assert ctx.state.boards.get(board.id) is None
    assert ctx.state.tasks.get(task.id) is None
    assert ctx.state.labels.get(l1.id) is None and ctx.state.labels.get(l2.id) is None
    assert ctx.state.labels.get(keep.id) is not None


def test_board_crud_and_ownership(ctx):
    alice = ctx.seed_user("alice@example.com")
    bob = ctx.seed_user("bob@example.com")

    r = ctx.client.post("/api/boards", json={"name": "Work", "summary": "s", "start_date": "2026-09-01"}, headers=ctx.auth(alice))
    assert r.status_code == 201
    board = r.json()
    assert list(board) == ["id", "user_id", "name", "summary", "start_date", "created_at", "updated_at"]
    assert board["user_id"] == alice.id and board["summary"] == "s" and board["start_date"] == "2026-09-01"

    assert ctx.client.post("/api/boards", json={"name": "  "}, headers=ctx.auth(alice)).json()["error"]["code"] == "invalid_name"
    assert [b["id"] for b in ctx.client.get("/api/boards", headers=ctx.auth(alice)).json()] == [board["id"]]
    assert ctx.client.get("/api/boards", headers=ctx.auth(bob)).json() == []

    # Non-owners get 404, never 403, for every per-board route.
    for method in ("put", "delete"):
        kwargs = {"json": {"name": "x"}} if method == "put" else {}
        r = getattr(ctx.client, method)(f"/api/boards/{board['id']}", headers=ctx.auth(bob), **kwargs)
        assert r.status_code == 404 and r.json()["error"] == {"code": "not_found", "message": "board not found"}

    r = ctx.client.put(f"/api/boards/{board['id']}", json={"name": "Renamed"}, headers=ctx.auth(alice))
    assert r.status_code == 200
    # PUT replaces all fields (Go decodes into a fresh boardRequest).
    assert r.json()["name"] == "Renamed" and r.json()["summary"] == "" and r.json()["start_date"] == ""
