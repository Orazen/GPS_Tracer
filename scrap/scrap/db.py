"""Database access and migrations for the scrap service.

Mirrors tacho/db.py. Migrations are ordered .sql files applied once and recorded
in scrap_schema_migrations with a SHA-256. No ORM.
"""

from __future__ import annotations

import hashlib
import logging
import os
from contextlib import contextmanager
from typing import Any, Iterator, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "migrations")


class MigrationError(RuntimeError):
    pass


def _psycopg():
    try:
        import psycopg  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("psycopg is required") from exc
    return psycopg


class Database:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._connection = None

    def connect(self):
        if self._connection is None or self._connection.closed:
            psycopg = _psycopg()
            self._connection = psycopg.connect(self.database_url, autocommit=False)
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

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
        except Exception:
            connection.rollback()
            raise
        connection.commit()

    @contextmanager
    def transaction(self) -> Iterator[Any]:
        """Run several statements in one transaction; commit on success, roll back on error.

        Use this for any write that also reads or returns rows (INSERT ... RETURNING,
        SELECT ... FOR UPDATE). fetch_one/fetch_all never commit.
        """
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                yield cursor
        except Exception:
            connection.rollback()
            raise
        connection.commit()

    def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> Optional[Tuple[Any, ...]]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return cursor.fetchone()
        except Exception:
            connection.rollback()
            raise

    def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
        except Exception:
            connection.rollback()
            raise

    def apply_migrations(self, migrations_dir: Optional[str] = None) -> List[str]:
        directory = migrations_dir or MIGRATIONS_DIR
        files = sorted(name for name in os.listdir(directory) if name.endswith(".sql"))
        if not files:
            raise MigrationError("no .sql migrations found in %s" % directory)
        self._ensure_ledger()
        applied_versions = {}
        for version, name, checksum in self.fetch_all(
            "SELECT version, name, checksum FROM scrap_schema_migrations"
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
                        "migration %d (%s) has changed since applied" % (version, name)
                    )
                continue
            connection = self.connect()
            try:
                with connection.cursor() as cursor:
                    cursor.execute(raw.decode("utf-8"))
                    cursor.execute(
                        "INSERT INTO scrap_schema_migrations (version, name, checksum) VALUES (%s, %s, %s)",
                        (version, filename, checksum),
                    )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                raise MigrationError("migration %d (%s) failed: %s" % (version, filename, exc)) from exc
            newly_applied.append(filename)
        return newly_applied

    def _ensure_ledger(self) -> None:
        self.execute(
            """
            CREATE TABLE IF NOT EXISTS scrap_schema_migrations (
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
                "SELECT tablename FROM pg_tables WHERE schemaname = current_schema() ORDER BY tablename"
            )
        ]


def rows_as_dicts(rows, columns):
    return [dict(zip(columns, row)) for row in rows]
