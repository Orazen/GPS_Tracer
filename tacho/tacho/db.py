"""Database access and migrations.

Migrations are ordered ``.sql`` files applied once and recorded in
``tacho_schema_migrations`` with a SHA-256 of their contents. If an already-applied
file changes, the runner **refuses to start** rather than skipping it: a silently
skipped migration is a schema that differs from what the code believes, which is
the kind of fault that surfaces weeks later as corrupted reporting.

No ORM. The queries this service runs are a few dozen lines of SQL each and
benefit from being readable by whoever has to check them.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")


class MigrationError(RuntimeError):
    """A migration is missing, altered, or failed to apply."""


def _psycopg():
    try:
        import psycopg  # noqa: F401
    except ImportError as exc:  # pragma: no cover - exercised only without deps
        raise RuntimeError(
            "psycopg is required for database access. Install requirements.txt."
        ) from exc
    return psycopg


class Database:
    """A thin wrapper around a psycopg connection.

    One connection per process with an explicit transaction boundary is enough
    here: the API is low-throughput and the worker processes one file at a time.
    """

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._connection = None

    # -- lifecycle --------------------------------------------------------
    def connect(self):
        if self._connection is None or self._connection.closed:
            psycopg = _psycopg()
            self._connection = psycopg.connect(
                self.database_url, autocommit=False, row_factory=None
            )
        return self._connection

    def close(self) -> None:
        if self._connection is not None and not self._connection.closed:
            self._connection.close()
        self._connection = None

    def __enter__(self) -> "Database":
        self.connect()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # -- queries ----------------------------------------------------------
    #
    # Every statement here rolls the transaction back when it fails, and that is
    # not tidiness. There is ONE connection per process, and PostgreSQL aborts the
    # whole transaction on a failed statement: it then refuses every later
    # statement on that connection with InFailedSqlTransaction until the
    # transaction is rolled back. Without the rollback below, a single failed
    # query -- an expected unique-violation, a probe against a table that does not
    # exist -- would poison every request that followed it until the process was
    # restarted, including the audit writes that are supposed to record what
    # happened. Found by a test that deliberately violates a unique index.
    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
        except Exception:
            connection.rollback()
            raise
        connection.commit()

    def fetch_one(
        self, sql: str, params: Sequence[Any] = ()
    ) -> Optional[Tuple[Any, ...]]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()
        except Exception:
            connection.rollback()
            raise

    def fetch_all(
        self, sql: str, params: Sequence[Any] = ()
    ) -> List[Tuple[Any, ...]]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
        except Exception:
            connection.rollback()
            raise

    # -- migrations -------------------------------------------------------
    def apply_migrations(self, migrations_dir: Optional[str] = None) -> List[str]:
        """Apply pending migrations; return the names applied.

        Idempotent: running it twice applies nothing the second time.
        """
        directory = migrations_dir or MIGRATIONS_DIR
        files = sorted(
            name for name in os.listdir(directory) if name.endswith(".sql")
        )
        if not files:
            raise MigrationError("no .sql migrations found in %s" % directory)

        self._ensure_ledger()

        applied_versions: dict = {}
        for version, name, checksum in self.fetch_all(
            "SELECT version, name, checksum FROM tacho_schema_migrations"
        ):
            applied_versions[version] = (name, checksum)

        newly_applied: List[str] = []
        for filename in files:
            version = int(filename.split("_", 1)[0])
            path = os.path.join(directory, filename)
            with open(path, "rb") as handle:
                raw = handle.read()
            checksum = hashlib.sha256(raw).hexdigest()

            if version in applied_versions:
                name, recorded = applied_versions[version]
                if recorded != checksum:
                    raise MigrationError(
                        "migration %d (%s) has changed since it was applied "
                        "(recorded %s, now %s). Migrations are immutable: add a new "
                        "file instead of editing an applied one."
                        % (version, name, recorded[:12], checksum[:12])
                    )
                continue

            logger.info("applying migration %d (%s)", version, filename)
            connection = self.connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(raw.decode("utf-8"))
                    cursor.execute(
                        "INSERT INTO tacho_schema_migrations (version, name, checksum) "
                        "VALUES (%s, %s, %s)",
                        (version, filename, checksum),
                    )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                raise MigrationError(
                    "migration %d (%s) failed: %s" % (version, filename, exc)
                ) from exc
            newly_applied.append(filename)

        return newly_applied

    def _ensure_ledger(self) -> None:
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS tacho_schema_migrations (
                version     INTEGER PRIMARY KEY,
                name        TEXT        NOT NULL,
                checksum    TEXT        NOT NULL,
                applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

    def table_names(self) -> List[str]:
        return [
            row[0]
            for row in self.fetch_all(
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() "
                "ORDER BY tablename"
            )
        ]


def rows_as_dicts(
    rows: Iterable[Tuple[Any, ...]], columns: Sequence[str]
) -> List[dict]:
    return [dict(zip(columns, row)) for row in rows]
