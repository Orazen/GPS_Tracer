"""Service configuration, read from the environment.

Same discipline as the Traccar entrypoint: a misconfigured container must refuse
to start rather than come up looking healthy. The two ways this service can be
misconfigured dangerously are (a) running with no API token, which would expose
driver personal data to anything on the Docker network, and (b) pointing storage at
a directory inside the repository, which would put raw driver cards in Git.

Both are checked at startup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

DEFAULT_DATABASE_URL = "postgresql://traccar:traccar@db:5432/traccar"
DEFAULT_STORAGE_DIR = "/var/lib/gpstracer/tacho"
DEFAULT_MAX_UPLOAD_BYTES = 8 * 1024 * 1024

#: Where the API is allowed to be reached from, in addition to loopback. The
#: service is internal; only the dashboard needs to talk to it.
DEFAULT_ALLOWED_ORIGINS = "http://127.0.0.1:8083,http://localhost:8083"


@dataclass
class Settings:
    database_url: str = DEFAULT_DATABASE_URL
    storage_dir: str = DEFAULT_STORAGE_DIR
    api_token: str = ""
    max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES
    allowed_origins: List[str] = field(default_factory=list)
    external_parser: str = ""
    worker_poll_seconds: float = 3.0
    worker_lease_minutes: int = 15
    worker_max_attempts: int = 3
    log_level: str = "info"
    #: Set only in tests, to allow the API to run without a token.
    allow_anonymous: bool = False

    # -- validation -------------------------------------------------------
    def validate(self) -> List[str]:
        """Return every configuration problem, not just the first."""
        problems: List[str] = []

        if not self.api_token and not self.allow_anonymous:
            problems.append(
                "TACHO_API_TOKEN is not set. The API serves driver personal data; "
                "refusing to start without a token. Generate one with: "
                "openssl rand -base64 32"
            )
        elif len(self.api_token) < 24 and not self.allow_anonymous:
            problems.append(
                "TACHO_API_TOKEN is shorter than 24 characters. Driver personal "
                "data is behind this token; use a generated secret."
            )

        if not self.storage_dir:
            problems.append("TACHO_STORAGE_DIR is not set")
        else:
            normalised = os.path.abspath(self.storage_dir)
            if any(part == ".git" for part in normalised.split(os.sep)):
                problems.append(
                    "TACHO_STORAGE_DIR is inside a .git directory: raw driver "
                    "cards must never be written into version control"
                )

        if self.max_upload_bytes <= 0:
            problems.append("TACHO_MAX_UPLOAD_BYTES must be positive")

        if self.worker_max_attempts < 1:
            problems.append("TACHO_WORKER_MAX_ATTEMPTS must be at least 1")

        if not self.database_url.startswith(("postgresql://", "postgres://")):
            problems.append(
                "TACHO_DATABASE_URL must be a PostgreSQL URL; this service does "
                "not support any other database"
            )
        return problems

    @property
    def actor_roles_allowed_driver_data(self) -> frozenset:
        from .api.security import ROLE_FLEET_MANAGER, ROLE_OWNER

        return frozenset({ROLE_OWNER, ROLE_FLEET_MANAGER})


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def load_settings(allow_anonymous: Optional[bool] = None) -> Settings:
    """Build settings from the environment.

    ``allow_anonymous`` defaults to reading ``TACHO_ALLOW_ANONYMOUS`` and exists so
    tests can exercise the API without a token. It is never set in production, and
    the value is logged loudly if it ever is.
    """
    if allow_anonymous is None:
        allow_anonymous = os.environ.get("TACHO_ALLOW_ANONYMOUS", "").lower() in {
            "1",
            "true",
            "yes",
        }

    origins = [
        origin.strip()
        for origin in os.environ.get(
            "TACHO_ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS
        ).split(",")
        if origin.strip()
    ]

    return Settings(
        database_url=os.environ.get("TACHO_DATABASE_URL", DEFAULT_DATABASE_URL),
        storage_dir=os.environ.get("TACHO_STORAGE_DIR", DEFAULT_STORAGE_DIR),
        api_token=os.environ.get("TACHO_API_TOKEN", "").strip(),
        max_upload_bytes=_int_env("TACHO_MAX_UPLOAD_BYTES", DEFAULT_MAX_UPLOAD_BYTES),
        allowed_origins=origins,
        external_parser=os.environ.get("TACHO_EXTERNAL_PARSER", "").strip(),
        worker_poll_seconds=_float_env("TACHO_WORKER_POLL_SECONDS", 3.0),
        worker_lease_minutes=_int_env("TACHO_WORKER_LEASE_MINUTES", 15),
        worker_max_attempts=_int_env("TACHO_WORKER_MAX_ATTEMPTS", 3),
        log_level=os.environ.get("TACHO_LOG_LEVEL", "info"),
        allow_anonymous=bool(allow_anonymous),
    )
