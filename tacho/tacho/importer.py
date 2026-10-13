"""Tachograph import pipeline.

Two phases, deliberately separated by a database row rather than a function call:

**Ingest** (runs in the API process, inside the upload request)
    hash the bytes, refuse anything too large or empty, store the original in
    private content-addressed storage, detect a duplicate, and queue a row.

**Process** (runs in the worker process)
    claim a queued row, parse it, write the normalised activity, mark the row done
    or failed.

That split is the specification's requirement that parsing is kept out of the web
request. It also means a parser that segfaults or hangs cannot take the API with
it, and a slow parse cannot hold an upload connection open.

Failure handling, in one place so it is easy to audit:
* a rejected file gets a stable ``error_code`` and a message a human can act on;
* attempts are counted, and a row that fails repeatedly stops being retried;
* a partial activity write is impossible: days and changes are written in one
  transaction, so a file either contributes all of its rows or none.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from . import PARSER_VERSION
from .config import Settings
from .db import Database
from .domain.activities import Activity, summarise_day
from .parsers import ParseResult, ParserRegistry, TachographError
from .storage import ObjectStore

logger = logging.getLogger(__name__)

STATUS_PENDING = "pending"
STATUS_PROCESSING = "processing"
STATUS_DONE = "done"
STATUS_FAILED = "failed"
STATUS_DUPLICATE = "duplicate"
STATUS_REJECTED = "rejected"

#: Statuses that count as "a usable copy of this content already exists".
_TERMINAL_SUCCESS = (STATUS_DONE,)
#: Statuses that should NOT block a re-upload of identical bytes. A file that
#: failed once must be retryable; otherwise a transient error permanently poisons
#: that exact file.
_RETRYABLE_PRIOR = (STATUS_FAILED, STATUS_REJECTED)


@dataclass
class IngestOutcome:
    import_id: int
    status: str
    sha256: str
    size_bytes: int
    duplicate_of: Optional[int] = None
    reason: Optional[str] = None

    @property
    def accepted_for_processing(self) -> bool:
        return self.status == STATUS_PENDING


@dataclass
class ProcessOutcome:
    import_id: int
    status: str
    days_written: int = 0
    changes_written: int = 0
    error_code: Optional[str] = None
    error_message: Optional[str] = None
    warnings: List[str] = field(default_factory=list)


def _jsonb(value: Any):
    """Adapt a Python object for a jsonb column, tolerating odd types."""
    try:
        from psycopg.types.json import Jsonb

        return Jsonb(json.loads(json.dumps(value, default=str)))
    except ImportError:  # pragma: no cover
        return json.dumps(value, default=str)


def driver_key_for(result: ParseResult, sha256: str) -> str:
    """A stable key identifying whose activity this is.

    A card number is the identity when we have one; the content hash is the
    fallback. The fallback is deliberately *opaque* rather than derived from a name,
    so an unidentified import never silently merges into a real driver's record.
    """
    if result.card and result.card.card_number:
        return "card:%s" % result.card.card_number
    if result.card and result.card.driver_identification:
        return "driver:%s" % result.card.driver_identification.strip()
    return "unknown:%s" % sha256[:12]


class TachographImporter:
    """Ingest and process tachograph files."""

    def __init__(
        self,
        db: Database,
        store: ObjectStore,
        registry: ParserRegistry,
        settings: Settings,
    ) -> None:
        self.db = db
        self.store = store
        self.registry = registry
        self.settings = settings

    # ------------------------------------------------------------------
    # Phase 1 — ingest
    # ------------------------------------------------------------------
    def ingest(
        self,
        filename: str,
        data: bytes,
        uploaded_by: str,
        declared_kind: str = "unknown",
    ) -> IngestOutcome:
        if not data:
            raise ValueError("the uploaded file is empty")

        size = len(data)
        if size > self.settings.max_upload_bytes:
            raise ValueError(
                "file is %d bytes, over the %d-byte limit"
                % (size, self.settings.max_upload_bytes)
            )

        sha256 = self.store.sha256_of(data)
        self.store.ensure_directories()
        stored = self.store.put(data, sha256=sha256)

        # Duplicate detection. An identical file that already parsed successfully is
        # recorded as a duplicate rather than re-parsed: import history stays intact,
        # and re-parsing would create a second set of activity rows for the same card
        # and day.
        duplicate_of = self._find_duplicate(sha256)

        status = STATUS_DUPLICATE if duplicate_of else STATUS_PENDING
        reason = (
            "identical content already imported as import %d" % duplicate_of
            if duplicate_of
            else None
        )

        row = self.db.fetch_one(
            """
            INSERT INTO tacho_imports (
                original_filename, content_sha256, size_bytes, uploaded_by,
                declared_kind, status, stored_path, is_duplicate, duplicate_of
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                filename,
                sha256,
                stored.size_bytes,
                uploaded_by,
                declared_kind,
                status,
                stored.path,
                duplicate_of is not None,
                duplicate_of,
            ),
        )
        import_id = int(row[0])

        self.audit(
            actor=uploaded_by,
            action="import.ingest",
            subject_type="import",
            subject_id=str(import_id),
            detail={
                "filename": filename,
                "sha256": sha256,
                "size_bytes": size,
                "duplicate_of": duplicate_of,
            },
        )

        if duplicate_of:
            logger.info(
                "import %d is a duplicate of %d (sha256 %s)",
                import_id,
                duplicate_of,
                sha256[:12],
            )

        return IngestOutcome(
            import_id=import_id,
            status=status,
            sha256=sha256,
            size_bytes=size,
            duplicate_of=duplicate_of,
            reason=reason,
        )

    def _find_duplicate(self, sha256: str) -> Optional[int]:
        row = self.db.fetch_one(
            """
            SELECT id FROM tacho_imports
            WHERE content_sha256 = %s AND status = ANY(%s)
            ORDER BY id
            LIMIT 1
            """,
            (sha256, list(_TERMINAL_SUCCESS)),
        )
        return int(row[0]) if row else None

    # ------------------------------------------------------------------
    # Phase 2 — process
    # ------------------------------------------------------------------
    def claim_next(self) -> Optional[Dict[str, Any]]:
        """Atomically take one pending import, or reclaim a stale one.

        ``FOR UPDATE SKIP LOCKED`` lets several worker containers run at once
        without a message broker and without two of them taking the same file. A
        row stuck in ``processing`` past its lease is reclaimed, because a worker
        that was killed mid-parse (or an OOM, or a container restart) must not
        leave a file queued forever.
        """
        row = self.db.fetch_one(
            """
            UPDATE tacho_imports
               SET status = %s,
                   claimed_at = now(),
                   attempts = attempts + 1
             WHERE id = (
                 SELECT id FROM tacho_imports
                  WHERE status = %s
                     OR (status = %s AND claimed_at < now() - make_interval(mins => %s))
                  ORDER BY
                    CASE WHEN status = %s THEN 0 ELSE 1 END,
                    id
                  FOR UPDATE SKIP LOCKED
                  LIMIT 1
             )
            RETURNING id, stored_path, content_sha256, original_filename,
                      declared_kind, attempts
            """,
            (
                STATUS_PROCESSING,
                STATUS_PENDING,
                STATUS_PROCESSING,
                self.settings.worker_lease_minutes,
                STATUS_PENDING,
            ),
        )
        self.db.connect().commit()
        if row is None:
            return None
        return {
            "id": int(row[0]),
            "stored_path": row[1],
            "content_sha256": row[2],
            "original_filename": row[3],
            "declared_kind": row[4],
            "attempts": int(row[5]),
        }

    def process(self, claimed: Dict[str, Any]) -> ProcessOutcome:
        """Parse one claimed import and persist its activity."""
        import_id = claimed["id"]
        try:
            data = self._read_object(claimed["content_sha256"])
        except OSError as exc:
            return self._fail(
                import_id,
                "object_missing",
                "the stored file for import %d could not be read: %s"
                % (import_id, exc),
            )

        try:
            result = self.registry.parse(data)
        except TachographError as exc:
            return self._fail(import_id, exc.code, str(exc))
        except Exception as exc:  # noqa: BLE001 - a parser crash is not a server crash
            logger.exception("unexpected parser failure on import %d", import_id)
            return self._fail(
                import_id, "parser_crash", "parser raised %s: %s" % (type(exc).__name__, exc)
            )

        driver_key = driver_key_for(result, claimed["content_sha256"])
        days_written, changes_written = self._persist_activity(
            import_id, driver_key, result
        )

        self._mark_done(import_id, result, driver_key, days_written)

        self.audit(
            actor="worker",
            action="import.processed",
            subject_type="import",
            subject_id=str(import_id),
            detail={
                "source_kind": result.source_kind,
                "generation": result.generation,
                "days": days_written,
                "changes": changes_written,
                "warnings": len(result.warnings),
            },
        )
        return ProcessOutcome(
            import_id=import_id,
            status=STATUS_DONE,
            days_written=days_written,
            changes_written=changes_written,
            warnings=list(result.warnings),
        )

    def _read_object(self, sha256: str) -> bytes:
        return self.store.read(sha256)

    def _persist_activity(
        self, import_id: int, driver_key: str, result: ParseResult
    ) -> tuple:
        """Write days and changes in one transaction.

        A file must contribute all of its rows or none: half a day's activity is
        worse than a failed import, because it looks like data.
        """
        connection = self.db.connect()
        days_written = 0
        changes_written = 0
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM tacho_activity_changes WHERE import_id = %s",
                    (import_id,),
                )
                cursor.execute(
                    "DELETE FROM tacho_activity_days WHERE import_id = %s", (import_id,)
                )

                for activity_day in result.days:
                    totals = summarise_day(activity_day)
                    cursor.execute(
                        """
                        INSERT INTO tacho_activity_days (
                            import_id, driver_key, day, presence_counter, distance_km,
                            minutes_driving, minutes_work, minutes_availability,
                            minutes_rest, uncovered_minutes, open_ended, warnings
                        ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                        RETURNING id
                        """,
                        (
                            import_id,
                            driver_key,
                            activity_day.day,
                            activity_day.presence_counter,
                            activity_day.distance_km,
                            totals.minutes_of(Activity.DRIVING),
                            totals.minutes_of(Activity.WORK),
                            totals.minutes_of(Activity.AVAILABILITY),
                            totals.minutes_of(Activity.BREAK_REST),
                            totals.uncovered_minutes,
                            totals.open_ended,
                            _jsonb(totals.warnings),
                        ),
                    )
                    day_id = cursor.fetchone()[0]
                    days_written += 1

                    for change in activity_day.changes:
                        cursor.execute(
                            """
                            INSERT INTO tacho_activity_changes (
                                import_id, day_id, day, minute_of_day, activity,
                                slot, crew, card_not_inserted
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                            """,
                            (
                                import_id,
                                day_id,
                                change.day,
                                change.minute_of_day,
                                int(change.activity),
                                change.slot,
                                change.crew,
                                change.card_not_inserted,
                            ),
                        )
                        changes_written += 1

                self._upsert_driver_card(cursor, result)

            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return days_written, changes_written

    @staticmethod
    def _upsert_driver_card(cursor, result: ParseResult) -> None:
        card = result.card
        if card is None or not card.card_number:
            return
        holder = result.holder
        cursor.execute(
            """
            INSERT INTO tacho_driver_cards (
                card_number, issuing_member_state, holder_surname, holder_first_names,
                holder_birth_date, issue_date, validity_begin, expiry_date
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (card_number) DO UPDATE SET
                last_seen_at = now(),
                holder_surname = COALESCE(EXCLUDED.holder_surname, tacho_driver_cards.holder_surname),
                holder_first_names = COALESCE(EXCLUDED.holder_first_names, tacho_driver_cards.holder_first_names),
                holder_birth_date = COALESCE(EXCLUDED.holder_birth_date, tacho_driver_cards.holder_birth_date),
                expiry_date = COALESCE(EXCLUDED.expiry_date, tacho_driver_cards.expiry_date)
            """,
            (
                card.card_number,
                card.issuing_member_state,
                holder.surname if holder else None,
                holder.first_names if holder else None,
                holder.birth_date if holder else None,
                card.issue_date,
                card.validity_begin,
                card.expiry_date,
            ),
        )

    def _mark_done(
        self, import_id: int, result: ParseResult, driver_key: str, days_written: int
    ) -> None:
        card = result.card
        holder = result.holder
        warnings = list(result.warnings)
        if days_written == 0:
            warnings.append(
                "no_activity_records: the file parsed, but contained no daily "
                "activity. For a vehicle-unit download this is expected in this "
                "build; see docs/LIVE-TACHO.md."
            )
        self.db.execute(
            """
            UPDATE tacho_imports SET
                status = %s,
                processed_at = now(),
                source_kind = %s,
                generation = %s,
                parser_name = %s,
                parser_version = %s,
                warnings = %s,
                raw_evidence = %s,
                card_number = %s,
                issuing_member_state = %s,
                holder_surname = %s,
                holder_first_names = %s,
                holder_birth_date = %s,
                card_issue_date = %s,
                card_validity_begin = %s,
                card_expiry_date = %s,
                error_code = NULL,
                error_message = NULL
            WHERE id = %s
            """,
            (
                STATUS_DONE,
                result.source_kind,
                result.generation,
                result.parser_name,
                result.parser_version or PARSER_VERSION,
                _jsonb(warnings),
                _jsonb(result.raw_evidence),
                card.card_number if card else None,
                card.issuing_member_state if card else None,
                holder.surname if holder else None,
                holder.first_names if holder else None,
                holder.birth_date if holder else None,
                card.issue_date if card else None,
                card.validity_begin if card else None,
                card.expiry_date if card else None,
                import_id,
            ),
        )

    def _fail(self, import_id: int, code: str, message: str) -> ProcessOutcome:
        row = self.db.fetch_one(
            "SELECT attempts FROM tacho_imports WHERE id = %s", (import_id,)
        )
        attempts = int(row[0]) if row else self.settings.worker_max_attempts
        exhausted = attempts >= self.settings.worker_max_attempts

        # 'rejected' once the attempts are exhausted, so the queue stops retrying a
        # file that will never parse. The error is preserved either way.
        status = STATUS_REJECTED if exhausted else STATUS_FAILED
        self.db.execute(
            """
            UPDATE tacho_imports SET
                status = %s, processed_at = now(), error_code = %s, error_message = %s
            WHERE id = %s
            """,
            (status, code, message, import_id),
        )
        self.audit(
            actor="worker",
            action="import.failed",
            subject_type="import",
            subject_id=str(import_id),
            detail={"error_code": code, "message": message, "attempts": attempts},
        )
        logger.warning("import %d failed (%s): %s", import_id, code, message)
        return ProcessOutcome(
            import_id=import_id,
            status=status,
            error_code=code,
            error_message=message,
        )

    # ------------------------------------------------------------------
    def audit(
        self,
        actor: str,
        action: str,
        subject_type: Optional[str] = None,
        subject_id: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
        actor_role: Optional[str] = None,
        source_ip: Optional[str] = None,
    ) -> None:
        """Write an audit row. Never raises: auditing must not break the request."""
        try:
            self.db.execute(
                """
                INSERT INTO tacho_audit_log
                    (actor, actor_role, action, subject_type, subject_id, detail, source_ip)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                """,
                (
                    actor,
                    actor_role,
                    action,
                    subject_type,
                    subject_id,
                    _jsonb(detail or {}),
                    source_ip,
                ),
            )
        except Exception:  # noqa: BLE001
            logger.exception("could not write an audit row for %s", action)
