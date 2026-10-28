"""Configuration for the scrap/inventory service, read from the environment.

Same discipline as the tachograph service: a misconfigured container must refuse
to start rather than come up looking healthy.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

DEFAULT_DATABASE_URL = "postgresql://traccar:traccar@db:5432/traccar"
DEFAULT_STORAGE_DIR = "/var/lib/gpstracer/scrap"
DEFAULT_MAX_UPLOAD_BYTES = 16 * 1024 * 1024
DEFAULT_ALLOWED_ORIGINS = "http://127.0.0.1:8083,http://localhost:8083"


@dataclass
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    storage_dir: str = DEFAULT_STORAGE_DIR
    api_token: str = ""
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    allowed_origins: List[str] = field(default_factory=list)
    log_level: str = "info"
    allow_anonymous: bool = False

    def validate(self) -> List[str]:
        problems: List[str] = []
        if not self.api_token and not self.allow_anonymous:
            problems.append(
                "SCRAP_API_TOKEN is not set. The API serves load and stock data; "
                "refusing to start without a token. Generate one with: "
                "openssl rand -base64 32"
            )
        elif len(self.api_token) < 24 and not self.allow_anonymous:
            problems.append("SCRAP_API_TOKEN is shorter than 24 characters.")
        if not self.storage_dir:
            problems.append("SCRAP_STORAGE_DIR is not set")
        if self.max_upload_bytes <= 0:
            problems.append("SCRAP_MAX_UPLOAD_BYTES must be positive")
        if not self.database_url.startswith(("postgresql://", "postgres://")):
            problems.append("SCRAP_DATABASE_URL must be a PostgreSQL URL.")
        return problems

    @property
    def actor_roles_allowed(self) -> frozenset:
        return frozenset({"owner", "fleet_manager", "admin"})


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_settings(allow_anonymous: Optional[bool] = None) -> Settings:
    if allow_anonymous is None:
        allow_anonymous = os.environ.get("SCRAP_ALLOW_ANONYMOUS", "").lower() in {
            "1",
            "true",
            "yes",
        }
    origins = [
        origin.strip()
        for origin in os.environ.get("SCRAP_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS).split(",")
        if origin.strip()
    ]
    return Settings(
        database_url=os.environ.get("SCRAP_DATABASE_URL", DEFAULT_DATABASE_URL),
        storage_dir=os.environ.get("SCRAP_STORAGE_DIR", DEFAULT_STORAGE_DIR),
        api_token=os.environ.get("SCRAP_API_TOKEN", "").strip(),
        max_upload_bytes=_int_env("SCRAP_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
        allowed_origins=origins,
        log_level=os.environ.get("SCRAP_LOG_LEVEL", "info"),
        allow_anonymous=bool(allow_anonymous),
    )
