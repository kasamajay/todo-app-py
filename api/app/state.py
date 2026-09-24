"""Application state shared by the routers: config, the stores, and the
signing secret. Built once at startup (see main.create_app) and attached to
app.state; routers reach it through get_state()."""

from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import Request

from .auth.secret import load_or_create_secret
from .config import Config
from .storage import AttachmentStore, BoardStore, LabelStore, TaskStore, UserStore


@dataclass
class AppState:
    config: Config
    secret: bytes
    users: UserStore
    boards: BoardStore
    tasks: TaskStore
    labels: LabelStore
    attachments: AttachmentStore

    @classmethod
    def load(cls, config: Config) -> "AppState":
        d = config.data_dir
        os.makedirs(os.path.join(d, "attachments"), exist_ok=True)
        return cls(
            config=config,
            users=UserStore(os.path.join(d, "users.json")),
            boards=BoardStore(os.path.join(d, "boards.json")),
            tasks=TaskStore(os.path.join(d, "tasks.json")),
            attachments=AttachmentStore(os.path.join(d, "attachments.json"), d),
            labels=LabelStore(os.path.join(d, "labels.json")),
            secret=load_or_create_secret(d),
        )


def get_state(request: Request) -> AppState:
    return request.app.state.todo
