"""A minimal JSON-file-backed collection store with atomic
(write-temp-then-rename) persistence - a port of todo-app's Go
internal/storage package. Each Store owns one JSON file ({id: entity}) and
keeps a full in-memory copy guarded by a lock, since the whole application
is a single process (uvicorn runs with exactly one worker for this reason).

The on-disk format is identical to the Go version's (json.MarshalIndent with
two-space indent, keys sorted as Go sorts map keys), so a data directory can
be moved between the two backends.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from typing import Callable, Generic, TypeVar

from .models import Attachment, Board, Label, Task, User

T = TypeVar("T")


def write_file_atomic(path: str, content: bytes) -> None:
    """Write bytes via a temp file in the same directory, fsync, then an
    atomic rename, so a crash mid-write never leaves a partial file."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=os.path.basename(path) + ".tmp-", dir=directory)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except FileNotFoundError:
            pass
        raise


class Store(Generic[T]):
    def __init__(self, path: str, from_dict: Callable[[dict], T], to_dict: Callable[[T], dict]):
        self._lock = threading.Lock()
        self._path = path
        self._to_dict = to_dict
        self._data: dict[str, T] = {}

        try:
            with open(path, "rb") as f:
                raw = f.read()
        except FileNotFoundError:
            self._persist()
            return
        if not raw.strip():
            return
        try:
            loaded = json.loads(raw)
        except ValueError as e:
            raise RuntimeError(f"parsing {path}: {e}") from e
        self._data = {k: from_dict(v) for k, v in (loaded or {}).items()}

    def _persist(self) -> None:
        payload = {k: self._to_dict(v) for k, v in sorted(self._data.items())}
        write_file_atomic(self._path, json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"))

    # Entities go in and come out as copies, matching Go's value semantics
    # (Store[T] holds T by value): a handler mutating an entity it fetched
    # changes nothing until it calls put(), so a rejected request can never
    # leave a half-applied change in memory.

    def get(self, id: str) -> T | None:
        with self._lock:
            v = self._data.get(id)
            return copy.deepcopy(v) if v is not None else None

    def list(self) -> list[T]:
        with self._lock:
            return [copy.deepcopy(v) for v in self._data.values()]

    def put(self, id: str, v: T) -> None:
        """Upsert v under id and persist the whole collection atomically,
        rolling the in-memory change back if the write fails."""
        with self._lock:
            existed = id in self._data
            prev = self._data.get(id)
            self._data[id] = copy.deepcopy(v)
            try:
                self._persist()
            except BaseException:
                if existed:
                    self._data[id] = prev  # type: ignore[assignment]
                else:
                    del self._data[id]
                raise

    def delete(self, id: str) -> None:
        with self._lock:
            if id not in self._data:
                return
            prev = self._data.pop(id)
            try:
                self._persist()
            except BaseException:
                self._data[id] = prev
                raise

    def find(self, pred: Callable[[T], bool]) -> list[T]:
        with self._lock:
            return [copy.deepcopy(v) for v in self._data.values() if pred(v)]


class UserStore(Store[User]):
    def __init__(self, path: str):
        super().__init__(path, User.from_dict, User.to_dict)

    def find_by_email(self, email: str) -> User | None:
        email = email.strip().lower()
        return next((u for u in self.list() if u.email.lower() == email), None)

    def find_by_reset_token(self, token: str) -> User | None:
        if not token:
            return None
        return next((u for u in self.list() if u.reset_token == token), None)

    def find_by_google_id(self, google_id: str) -> User | None:
        if not google_id:
            return None
        return next((u for u in self.list() if u.google_id == google_id), None)


class BoardStore(Store[Board]):
    def __init__(self, path: str):
        super().__init__(path, Board.from_dict, Board.to_dict)

    def list_by_user(self, user_id: str) -> list[Board]:
        return self.find(lambda b: b.user_id == user_id)


class TaskStore(Store[Task]):
    def __init__(self, path: str):
        super().__init__(path, Task.from_dict, Task.to_dict)

    def list_by_user(self, user_id: str) -> list[Task]:
        return self.find(lambda t: t.user_id == user_id)

    def list_by_board(self, user_id: str, board_id: str) -> list[Task]:
        return self.find(lambda t: t.user_id == user_id and t.board_id == board_id)

    def list_by_board_any(self, board_id: str) -> list[Task]:
        return self.find(lambda t: t.board_id == board_id)


class LabelStore(Store[Label]):
    def __init__(self, path: str):
        super().__init__(path, Label.from_dict, Label.to_dict)

    def list_by_board(self, user_id: str, board_id: str) -> list[Label]:
        return self.find(lambda l: l.user_id == user_id and l.board_id == board_id)

    def list_by_board_any(self, board_id: str) -> list[Label]:
        return self.find(lambda l: l.board_id == board_id)


class AttachmentStore(Store[Attachment]):
    def __init__(self, path: str, data_dir: str):
        super().__init__(path, Attachment.from_dict, Attachment.to_dict)
        self._data_dir = data_dir

    def list_by_task(self, task_id: str) -> list[Attachment]:
        return self.find(lambda a: a.task_id == task_id)

    def blob_path(self, attachment_id: str) -> str:
        return os.path.join(self._data_dir, "attachments", attachment_id)

    def write_blob(self, attachment_id: str, content: bytes) -> None:
        write_file_atomic(self.blob_path(attachment_id), content)

    def read_blob(self, attachment_id: str) -> bytes:
        with open(self.blob_path(attachment_id), "rb") as f:
            return f.read()

    def delete_blob(self, attachment_id: str) -> None:
        try:
            os.remove(self.blob_path(attachment_id))
        except FileNotFoundError:
            pass
