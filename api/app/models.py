"""Entity models. Field names, field order, and omitempty behaviour mirror the
Go structs in todo-app's api/internal/models/models.go exactly, so API
responses are identical and data files are interchangeable between the Go
and Python backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .jsonfmt import ZERO_TIME, b64decode, b64encode, format_time, now, parse_time

# The fixed palette labels may use. web/src/theme.js's labelColors mirrors
# this exact list (same hex values, same order) - kept in sync manually.
LABEL_COLORS = [
    "#6366f1",  # brand indigo
    "#ef4444",  # danger red
    "#f59e0b",  # warning amber
    "#16a34a",  # success green
    "#0ea5e9",  # blue
    "#8b5cf6",  # purple
    "#ec4899",  # pink
    "#6b7280",  # gray
]

STATUS_TODO = "todo"
STATUS_IN_PROGRESS = "in_progress"
STATUS_DONE = "done"
VALID_STATUSES = (STATUS_TODO, STATUS_IN_PROGRESS, STATUS_DONE)


def is_valid_label_color(c: str) -> bool:
    return c in LABEL_COLORS


def _t(d: dict, key: str) -> datetime:
    v = d.get(key)
    return parse_time(v) if v else ZERO_TIME


@dataclass
class User:
    id: str
    email: str
    # None mirrors a nil []byte in Go (JSON null) - e.g. a Google-only account.
    password_hash: bytes | None = None
    salt: bytes | None = None
    google_id: str = ""
    is_admin: bool = False
    failed_login_count: int = 0
    locked_until: datetime = ZERO_TIME
    reset_token: str = ""
    reset_token_expires: datetime = ZERO_TIME
    # Two-factor auth: opt-in per account (see decisions/0011). two_factor_code
    # et al. hold a pending login challenge and are cleared once verified,
    # expired, or invalidated after too many wrong attempts.
    two_factor_enabled: bool = False
    two_factor_code: str = ""
    two_factor_code_expires: datetime = ZERO_TIME
    two_factor_attempts: int = 0
    created_at: datetime = ZERO_TIME

    def is_locked(self) -> bool:
        return now() < self.locked_until

    def public(self) -> dict:
        """The representation safe to send to clients (no secrets)."""
        return {
            "id": self.id,
            "email": self.email,
            "is_admin": self.is_admin,
            "failed_login_count": self.failed_login_count,
            "locked_until": format_time(self.locked_until),
            "two_factor_enabled": self.two_factor_enabled,
            "created_at": format_time(self.created_at),
        }

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "email": self.email,
            "password_hash": b64encode(self.password_hash),
            "salt": b64encode(self.salt),
        }
        if self.google_id:
            d["google_id"] = self.google_id
        d["is_admin"] = self.is_admin
        d["failed_login_count"] = self.failed_login_count
        d["locked_until"] = format_time(self.locked_until)
        if self.reset_token:
            d["reset_token"] = self.reset_token
        d["reset_token_expires"] = format_time(self.reset_token_expires)
        d["two_factor_enabled"] = self.two_factor_enabled
        if self.two_factor_code:
            d["two_factor_code"] = self.two_factor_code
        d["two_factor_code_expires"] = format_time(self.two_factor_code_expires)
        if self.two_factor_attempts:
            d["two_factor_attempts"] = self.two_factor_attempts
        d["created_at"] = format_time(self.created_at)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> User:
        return cls(
            id=d.get("id", ""),
            email=d.get("email", ""),
            password_hash=b64decode(d.get("password_hash")),
            salt=b64decode(d.get("salt")),
            google_id=d.get("google_id", "") or "",
            is_admin=bool(d.get("is_admin", False)),
            failed_login_count=int(d.get("failed_login_count", 0) or 0),
            locked_until=_t(d, "locked_until"),
            reset_token=d.get("reset_token", "") or "",
            reset_token_expires=_t(d, "reset_token_expires"),
            two_factor_enabled=bool(d.get("two_factor_enabled", False)),
            two_factor_code=d.get("two_factor_code", "") or "",
            two_factor_code_expires=_t(d, "two_factor_code_expires"),
            two_factor_attempts=int(d.get("two_factor_attempts", 0) or 0),
            created_at=_t(d, "created_at"),
        )


@dataclass
class Board:
    id: str
    user_id: str
    name: str
    summary: str = ""
    start_date: str = ""
    created_at: datetime = ZERO_TIME
    updated_at: datetime = ZERO_TIME

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "name": self.name,
            "summary": self.summary,
            "start_date": self.start_date,
            "created_at": format_time(self.created_at),
            "updated_at": format_time(self.updated_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Board:
        return cls(
            id=d.get("id", ""),
            user_id=d.get("user_id", ""),
            name=d.get("name", ""),
            summary=d.get("summary", "") or "",
            start_date=d.get("start_date", "") or "",
            created_at=_t(d, "created_at"),
            updated_at=_t(d, "updated_at"),
        )


@dataclass
class Label:
    id: str
    user_id: str
    board_id: str
    name: str
    color: str
    created_at: datetime = ZERO_TIME

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "board_id": self.board_id,
            "name": self.name,
            "color": self.color,
            "created_at": format_time(self.created_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Label:
        return cls(
            id=d.get("id", ""),
            user_id=d.get("user_id", ""),
            board_id=d.get("board_id", ""),
            name=d.get("name", ""),
            color=d.get("color", ""),
            created_at=_t(d, "created_at"),
        )


@dataclass
class Task:
    id: str
    user_id: str
    board_id: str
    title: str
    description: str = ""
    status: str = STATUS_TODO
    due_date: datetime | None = None
    label_ids: list[str] = field(default_factory=list)
    created_at: datetime = ZERO_TIME
    updated_at: datetime = ZERO_TIME

    def to_dict(self) -> dict:
        d: dict = {
            "id": self.id,
            "user_id": self.user_id,
            "board_id": self.board_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
        }
        # Both omitempty in Go: a nil *time.Time and a nil/empty slice are
        # left out entirely (the frontend treats a missing key as "none").
        if self.due_date is not None:
            d["due_date"] = format_time(self.due_date)
        if self.label_ids:
            d["label_ids"] = list(self.label_ids)
        d["created_at"] = format_time(self.created_at)
        d["updated_at"] = format_time(self.updated_at)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Task:
        due = d.get("due_date")
        return cls(
            id=d.get("id", ""),
            user_id=d.get("user_id", ""),
            board_id=d.get("board_id", ""),
            title=d.get("title", ""),
            description=d.get("description", "") or "",
            status=d.get("status", STATUS_TODO),
            due_date=parse_time(due) if due else None,
            label_ids=list(d.get("label_ids") or []),
            created_at=_t(d, "created_at"),
            updated_at=_t(d, "updated_at"),
        )


@dataclass
class Attachment:
    id: str
    task_id: str
    user_id: str
    filename: str
    content_type: str
    size_bytes: int
    created_at: datetime = ZERO_TIME

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "user_id": self.user_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "created_at": format_time(self.created_at),
        }

    @classmethod
    def from_dict(cls, d: dict) -> Attachment:
        return cls(
            id=d.get("id", ""),
            task_id=d.get("task_id", ""),
            user_id=d.get("user_id", ""),
            filename=d.get("filename", ""),
            content_type=d.get("content_type", ""),
            size_bytes=int(d.get("size_bytes", 0) or 0),
            created_at=_t(d, "created_at"),
        )
