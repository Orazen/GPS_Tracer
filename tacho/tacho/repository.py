"""Read queries.

Kept apart from the HTTP layer so the SQL can be reviewed on its own, and so the
coverage calculation — which is what lets the UI say "unknown" precisely — is not
buried inside a route handler.

Everything here returns plain tuples or dicts. No rows ever include the stored
file path: the specification forbids exposing originals, so the path is not even
selected by any query in this module.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Sequence

from .db import Database
from .domain.activities import Activity, ActivityChange, ActivityDay, build_spans, summarise_day
from .rules.driving_time import DayInput

IMPORT_LIST_COLUMNS = (
    "id",
    "original_filename",
    "content_sha256",
    "size_bytes",
    "uploaded_at",
    "uploaded_by",
    "declared_kind",
    "source_kind",
    "generation",
    "status",
    "attempts",
    "processed_at",
    "parser_name",
    "parser_version",
    "error_code",
    "error_message",
    "warnings",
    "card_number",
    "holder_surname",
    "holder_first_names",
    "is_duplicate",
    "duplicate_of",
)

DAY_COLUMNS = (
    "id",
    "import_id",
    "driver_key",
    "day",
    "presence_counter",
    "distance_km",
    "minutes_driving",
    "minutes_work",
    "minutes_availability",
    "minutes_rest",
    "uncovered_minutes",
    "open_ended",
    "warnings",
)


class ImportRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- imports ---------------------------------------------------------
    def list_imports(
        self,
        status: Optional[str] = None,
        card_number: Optional[str] = None,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if status:
            clauses.append("status = %s")
            params.append(status)
        if card_number:
            clauses.append("card_number = %s")
            params.append(card_number)
        if date_from:
            clauses.append("uploaded_at >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("uploaded_at < %s")
            params.append(date_to + _dt.timedelta(days=1))
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([min(max(limit, 1), 500), max(offset, 0)])

        rows = self.db.fetch_all(
            "SELECT %s FROM tacho_imports%s ORDER BY uploaded_at DESC LIMIT %%s OFFSET %%s"
            % (", ".join(IMPORT_LIST_COLUMNS), where),
            params,
        )
        return [dict(zip(IMPORT_LIST_COLUMNS, row)) for row in rows]

    def get_import(self, import_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetch_one(
            "SELECT %s, raw_evidence FROM tacho_imports WHERE id = %%s"
            % ", ".join(IMPORT_LIST_COLUMNS),
            (import_id,),
        )
        if row is None:
            return None
        record = dict(zip(IMPORT_LIST_COLUMNS + ("raw_evidence",), row))
        record["day_count"] = self.db.fetch_one(
            "SELECT count(*) FROM tacho_activity_days WHERE import_id = %s", (import_id,)
        )[0]
        return record

    def import_timeline(self, import_id: int) -> List[Dict[str, Any]]:
        columns = (
            "day",
            "minute_of_day",
            "activity",
            "slot",
            "crew",
            "card_not_inserted",
        )
        rows = self.db.fetch_all(
            "SELECT %s FROM tacho_activity_changes WHERE import_id = %%s "
            "ORDER BY day, minute_of_day, slot" % ", ".join(columns),
            (import_id,),
        )
        return [
            dict(zip(columns, row), activity_label=Activity(row[2]).label_en)
            for row in rows
        ]

    # -- activity --------------------------------------------------------
    def list_days(
        self,
        driver_key: Optional[str] = None,
        date_from: Optional[_dt.date] = None,
        date_to: Optional[_dt.date] = None,
        limit: int = 400,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if driver_key:
            clauses.append("driver_key = %s")
            params.append(driver_key)
        if date_from:
            clauses.append("day >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("day <= %s")
            params.append(date_to)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(min(max(limit, 1), 2000))
        rows = self.db.fetch_all(
            "SELECT %s FROM tacho_activity_days%s ORDER BY day DESC LIMIT %%s"
            % (", ".join(DAY_COLUMNS), where),
            params,
        )
        return [dict(zip(DAY_COLUMNS, row)) for row in rows]

    def list_driver_cards(self) -> List[Dict[str, Any]]:
        columns = (
            "card_number",
            "issuing_member_state",
            "holder_surname",
            "holder_first_names",
            "holder_birth_date",
            "issue_date",
            "expiry_date",
            "first_seen_at",
            "last_seen_at",
        )
        rows = self.db.fetch_all(
            "SELECT %s FROM tacho_driver_cards ORDER BY last_seen_at DESC"
            % ", ".join(columns)
        )
        return [dict(zip(columns, row)) for row in rows]

    def day_inputs(
        self,
        driver_key: str,
        period_start: Optional[_dt.date] = None,
        period_end: Optional[_dt.date] = None,
    ) -> List[DayInput]:
        """Reconstruct engine inputs from stored activity.

        Rebuilt from the ``tacho_activity_changes`` rows rather than from the
        stored per-day totals, so a calculation always reflects the recorded
        evidence and cannot drift from a stored figure that was computed by an
        older version.
        """
        clauses = ["driver_key = %s"]
        params: List[Any] = [driver_key]
        if period_start:
            clauses.append("day >= %s")
            params.append(period_start)
        if period_end:
            clauses.append("day <= %s")
            params.append(period_end)

        rows = self.db.fetch_all(
            """
            SELECT d.day, d.import_id, d.presence_counter, c.day_id, c.minute_of_day,
                   c.activity, c.slot, c.crew, c.card_not_inserted
              FROM tacho_activity_days d
              LEFT JOIN tacho_activity_changes c ON c.day_id = d.id
             WHERE %s
             ORDER BY d.day, c.minute_of_day, c.slot
            """
            % " AND ".join("d." + clause for clause in clauses),
            params,
        )

        grouped: Dict[_dt.date, Dict[str, Any]] = {}
        for day, import_id, presence, day_id, minute, activity, slot, crew, no_card in rows:
            entry = grouped.setdefault(
                day,
                {
                    "import_id": import_id,
                    "presence_counter": presence,
                    "changes": [],
                    "distance_km": None,
                },
            )
            if minute is not None:
                entry["changes"].append(
                    ActivityChange(
                        day=day,
                        minute_of_day=int(minute),
                        activity=Activity(int(activity)),
                        slot=int(slot or 0),
                        crew=bool(crew),
                        card_not_inserted=bool(no_card),
                    )
                )

        day_inputs: List[DayInput] = []
        for day in sorted(grouped):
            entry = grouped[day]
            activity_day = ActivityDay(
                day=day,
                presence_counter=entry["presence_counter"],
                distance_km=entry["distance_km"],
                changes=tuple(entry["changes"]),
            )
            totals = summarise_day(activity_day)
            day_inputs.append(
                DayInput(
                    day=day,
                    spans=tuple(build_spans(activity_day)),
                    uncovered_minutes=totals.uncovered_minutes,
                    open_ended=totals.open_ended,
                    import_id=entry["import_id"],
                )
            )
        return day_inputs

    # -- coverage --------------------------------------------------------
    def coverage(
        self, driver_key: str, date_from: _dt.date, date_to: _dt.date
    ) -> Dict[str, Any]:
        """Which days exist, which are missing, and what that invalidates.

        This is the query behind the "file coverage and missing-data warnings"
        requirement. It answers, for every day in the requested span: is there
        recorded activity, how complete is it, and therefore which findings can be
        trusted.
        """
        rows = self.db.fetch_all(
            """
            SELECT day, import_id, uncovered_minutes, open_ended,
                   minutes_driving + minutes_work + minutes_availability + minutes_rest
                       + uncovered_minutes AS accounted_minutes
              FROM tacho_activity_days
             WHERE driver_key = %s AND day BETWEEN %s AND %s
             ORDER BY day
            """,
            (driver_key, date_from, date_to),
        )
        present = {row[0]: row for row in rows}

        missing: List[str] = []
        incomplete: List[Dict[str, Any]] = []
        complete: List[str] = []
        cursor = date_from
        while cursor <= date_to:
            row = present.get(cursor)
            if row is None:
                missing.append(cursor.isoformat())
            elif row[2]:
                incomplete.append(
                    {
                        "day": cursor.isoformat(),
                        "uncovered_minutes": int(row[2]),
                        "open_ended": bool(row[3]),
                        "import_id": int(row[1]),
                    }
                )
            else:
                complete.append(cursor.isoformat())
            cursor += _dt.timedelta(days=1)

        total_days = (date_to - date_from).days + 1
        warnings: List[str] = []
        if missing:
            warnings.append(
                "%d of %d days have no imported record: %s"
                % (len(missing), total_days, ", ".join(missing[:10]))
            )
        if incomplete:
            warnings.append(
                "%d day(s) have recorded time without a card; activity there is "
                "unknown" % len(incomplete)
            )

        return {
            "driver_key": driver_key,
            "period_start": date_from.isoformat(),
            "period_end": date_to.isoformat(),
            "total_days": total_days,
            "days_with_a_record": len(present),
            "days_complete": complete,
            "days_incomplete": incomplete,
            "days_missing": missing,
            "coverage_ratio": round(len(present) / total_days, 4) if total_days else 0.0,
            "warnings": warnings,
            # Stated explicitly so the caller cannot mistake partial coverage for a
            # complete picture.
            "rest_findings_reliable": not missing and not incomplete,
        }

    # -- calculations ----------------------------------------------------
    def save_calculation(
        self,
        result,
        actor: str,
        actor_role: Optional[str] = None,
    ) -> int:
        from .importer import _jsonb

        payload = result.as_dict()
        row = self.db.fetch_one(
            """
            INSERT INTO tacho_calculations (
                driver_key, period_start, period_end, rules_version, engine_version,
                status, source_days, missing_days, source_import_ids, result,
                assumptions, warnings, validated_against_reference, validation_note
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING id
            """,
            (
                result.driver_key,
                result.period_start,
                result.period_end,
                result.rules_version,
                result.engine_version,
                result.status,
                result.source_days,
                result.missing_days,
                result.source_import_ids,
                _jsonb(payload),
                _jsonb(result.assumptions),
                _jsonb(result.warnings),
                result.validated_against_reference,
                result.validation_note,
            ),
        )
        return int(row[0])

    def get_calculation(self, calculation_id: int) -> Optional[Dict[str, Any]]:
        columns = (
            "id",
            "computed_at",
            "driver_key",
            "period_start",
            "period_end",
            "rules_version",
            "engine_version",
            "status",
            "source_days",
            "missing_days",
            "source_import_ids",
            "result",
            "assumptions",
            "warnings",
            "validated_against_reference",
            "validation_note",
        )
        row = self.db.fetch_one(
            "SELECT %s FROM tacho_calculations WHERE id = %%s" % ", ".join(columns),
            (calculation_id,),
        )
        return dict(zip(columns, row)) if row else None

    def list_calculations(
        self, driver_key: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        columns = (
            "id",
            "computed_at",
            "driver_key",
            "period_start",
            "period_end",
            "rules_version",
            "status",
            "validated_against_reference",
        )
        if driver_key:
            rows = self.db.fetch_all(
                "SELECT %s FROM tacho_calculations WHERE driver_key = %%s "
                "ORDER BY computed_at DESC LIMIT %%s" % ", ".join(columns),
                (driver_key, min(max(limit, 1), 500)),
            )
        else:
            rows = self.db.fetch_all(
                "SELECT %s FROM tacho_calculations ORDER BY computed_at DESC LIMIT %%s"
                % ", ".join(columns),
                (min(max(limit, 1), 500),),
            )
        return [dict(zip(columns, row)) for row in rows]

    # -- audit -----------------------------------------------------------
    def audit_trail(
        self, subject_type: Optional[str] = None, limit: int = 100
    ) -> List[Dict[str, Any]]:
        columns = ("id", "at", "actor", "actor_role", "action", "subject_type", "subject_id", "detail")
        if subject_type:
            rows = self.db.fetch_all(
                "SELECT %s FROM tacho_audit_log WHERE subject_type = %%s "
                "ORDER BY at DESC LIMIT %%s" % ", ".join(columns),
                (subject_type, min(max(limit, 1), 500)),
            )
        else:
            rows = self.db.fetch_all(
                "SELECT %s FROM tacho_audit_log ORDER BY at DESC LIMIT %%s"
                % ", ".join(columns),
                (min(max(limit, 1), 500),),
            )
        return [dict(zip(columns, row)) for row in rows]
