"""Shared fixtures. Every test gets a fresh app on its own temp DATA_DIR, the
counterpart of the Go tests' t.TempDir() stores."""

import os

# Importing app.main must not build the module-level app against ./data.
os.environ["TODO_APP_NO_AUTOCREATE"] = "1"

from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.auth import passwords, tokens  # noqa: E402
from app.config import Config  # noqa: E402
from app.idgen import new_id  # noqa: E402
from app.jsonfmt import now  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Board, Label, Task, User  # noqa: E402

REDIRECT_URI = "http://localhost:5173/api/auth/google/callback"
FRONTEND = "http://localhost:5173"


def make_config(data_dir, google: bool = False) -> Config:
    return Config(
        data_dir=str(data_dir),
        google_client_id="test-client-id" if google else "",
        google_client_secret="test-client-secret" if google else "",
        google_redirect_uri=REDIRECT_URI,
        frontend_base_url=FRONTEND,
    )


class Ctx:
    """A running test app plus helpers to seed data straight into its stores."""

    def __init__(self, data_dir, google: bool = False):
        self.app = create_app(make_config(data_dir, google))
        self.state = self.app.state.todo
        self.client = TestClient(self.app, follow_redirects=False)

    def seed_user(self, email: str, password: str | None = None, two_factor: bool = False, **extra) -> User:
        user = User(id=new_id(), email=email, two_factor_enabled=two_factor, created_at=now(), **extra)
        if password is not None:
            user.password_hash, user.salt = passwords.hash_password(password)
        self.state.users.put(user.id, user)
        return user

    def auth(self, user: User) -> dict:
        token = tokens.mint(self.state.secret, tokens.Claims(user.id, user.is_admin, now() + timedelta(hours=1)))
        return {"Authorization": "Bearer " + token}

    def seed_board(self, user: User, name: str = "Board") -> Board:
        ts = now()
        b = Board(id=new_id(), user_id=user.id, name=name, created_at=ts, updated_at=ts)
        self.state.boards.put(b.id, b)
        return b

    def seed_label(self, user: User, board: Board, name: str = "Label", color: str = "#6366f1") -> Label:
        label = Label(id=new_id(), user_id=user.id, board_id=board.id, name=name, color=color, created_at=now())
        self.state.labels.put(label.id, label)
        return label

    def seed_task(self, user: User, board: Board, title: str = "Task", label_ids=None) -> Task:
        ts = now()
        t = Task(
            id=new_id(), user_id=user.id, board_id=board.id, title=title,
            label_ids=list(label_ids or []), created_at=ts, updated_at=ts,
        )
        self.state.tasks.put(t.id, t)
        return t


@pytest.fixture
def ctx(tmp_path):
    return Ctx(tmp_path)


@pytest.fixture
def gctx(tmp_path):
    """An app with Google OAuth configured (test client id/secret)."""
    return Ctx(tmp_path, google=True)
