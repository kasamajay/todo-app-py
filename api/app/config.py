"""Environment configuration - the same variable names and defaults as the Go API."""

import os
from dataclasses import dataclass


def _env(key: str, fallback: str) -> str:
    v = os.environ.get(key, "")
    return v if v else fallback


@dataclass(frozen=True)
class Config:
    data_dir: str
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str
    frontend_base_url: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            data_dir=_env("DATA_DIR", "./data"),
            google_client_id=_env("GOOGLE_CLIENT_ID", ""),
            google_client_secret=_env("GOOGLE_CLIENT_SECRET", ""),
            google_redirect_uri=_env("GOOGLE_REDIRECT_URI", "http://localhost:5173/api/auth/google/callback"),
            frontend_base_url=_env("FRONTEND_BASE_URL", "http://localhost:5173"),
        )

    @property
    def google_configured(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)
