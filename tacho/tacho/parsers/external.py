"""External parser adapter.

The contract is deliberately coarse so that any language and any licence model can
sit behind it without linking into this process: the configured command reads a
tachograph download on **stdin** and writes a **JSON** result on **stdout**.

``way-platform/tachograph-go`` (MIT) is the intended partner for VU downloads and
for GEN2/GEN2v2, which the clean-room parser does not attempt. Install or wrap it
and point ``TACHO_EXTERNAL_PARSER`` at it.

Expected JSON on stdout::

    {
      "source_kind": "driver_card" | "vehicle_unit",
      "generation": "gen1" | "gen2" | "gen2v2",
      "parser_version": "optional string",
      "card":   {"card_number": "...", "issuing_member_state": 5,
                 "issue_date": "2024-03-01", "expiry_date": "2029-03-01"},
      "holder": {"surname": "...", "first_names": "...",
                 "birth_date": "1980-04-12"},
      "vehicle_unit": {"serial_number": "...", "registration": "AB123CD"},
      "days": [
        {"date": "2026-09-14",
         "presence_counter": 12,
         "distance_km": 220,
         "changes": [
           {"minute": 375, "activity": 3, "slot": 0,
            "crew": false, "card_not_inserted": false}
         ]}
      ],
      "warnings": ["free text"]
    }

Anything the command writes on stderr is captured and attached to the warnings so
a failure inside a third-party parser is diagnosable instead of invisible.

Testing status, stated precisely because it is easy to overstate: the adapter itself
is covered by 22 tests that drive it with **stub commands**, so the JSON mapping,
the malformed-payload handling and every failure mode (timeout, non-zero exit,
missing binary, unparsable JSON, oversized output) are exercised. What is **not**
verified is any real external parser: no such binary is installed, so
``tachograph-go`` itself has never been invoked from here. See
``docs/TACHO-SERVICE.md`` §5.
"""

from __future__ import annotations

import datetime as _dt
import json
import shlex
import subprocess
from typing import Any, Dict, List, Optional

from .base import (
    DRIVER_CARD,
    GEN1,
    GEN2,
    GEN2V2,
    UNKNOWN,
    VEHICLE_UNIT,
    CardHolder,
    CardIdentification,
    ParseResult,
    VehicleUnitIdentification,
)
from .errors import (
    ParserTimeoutError,
    ParserUnavailableError,
    UnsupportedFileError,
)
from ..domain.activities import Activity, ActivityChange, ActivityDay

DEFAULT_TIMEOUT_SECONDS = 30
MAX_OUTPUT_BYTES = 8 * 1024 * 1024

_KINDS = {DRIVER_CARD, VEHICLE_UNIT, UNKNOWN}
_GENERATIONS = {GEN1, GEN2, GEN2V2}


def _parse_date(value: Any, field: str, warnings: List[str]) -> Optional[_dt.date]:
    if value in (None, ""):
        return None
    if isinstance(value, _dt.date) and not isinstance(value, _dt.datetime):
        return value
    try:
        return _dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        warnings.append("external_parser_unparsable_%s=%r" % (field, value))
        return None


class ExternalCommandParser:
    """Run a configured external parser as a subprocess."""

    def __init__(
        self, command: str, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self.command = command
        self.timeout_seconds = timeout_seconds
        #: Set in ``name`` so failures identify which adapter was configured.
        self.name = "external:%s" % command
        self.version = "external-unverified"

    # -- protocol ---------------------------------------------------------
    def supports(self, data: bytes) -> bool:
        """Always True: an external parser is authoritative by configuration.

        The clean-room parser runs first, so this is only reached for files it
        could not handle. Refusing here would make the adapter useless for exactly
        the case it exists for.
        """
        return bool(data)

    def parse(self, data: bytes) -> ParseResult:
        try:
            argv = shlex.split(self.command)
        except ValueError as exc:
            raise ParserUnavailableError("invalid TACHO_EXTERNAL_PARSER: %s" % exc)
        if not argv:
            raise ParserUnavailableError("TACHO_EXTERNAL_PARSER is empty")

        try:
            completed = subprocess.run(  # noqa: S603 - argv is operator-supplied config
                argv,
                input=data,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            raise ParserUnavailableError(
                "external parser '%s' not found: %s" % (argv[0], exc)
            )
        except subprocess.TimeoutExpired:
            raise ParserTimeoutError(
                "external parser '%s' exceeded %ds"
                % (argv[0], self.timeout_seconds)
            )

        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        if completed.returncode != 0:
            raise UnsupportedFileError(
                "external parser '%s' exited %d: %s"
                % (argv[0], completed.returncode, stderr[-500:] or "no stderr")
            )

        if len(completed.stdout) > MAX_OUTPUT_BYTES:
            raise UnsupportedFileError(
                "external parser produced %d bytes of JSON; refusing to load it"
                % len(completed.stdout)
            )

        try:
            payload = json.loads(completed.stdout.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as exc:
            raise UnsupportedFileError(
                "external parser did not produce valid JSON: %s" % exc
            )
        if not isinstance(payload, dict):
            raise UnsupportedFileError("external parser JSON must be an object")

        return self._to_result(payload, stderr)

    # -- payload mapping --------------------------------------------------
    def _to_result(self, payload: Dict[str, Any], stderr: str) -> ParseResult:
        warnings: List[str] = [str(w) for w in payload.get("warnings", [])]
        if stderr:
            warnings.append("external_parser_stderr=%s" % stderr[-500:])

        kind = str(payload.get("source_kind") or UNKNOWN).lower()
        if kind not in _KINDS:
            warnings.append("external_parser_unknown_source_kind=%r" % kind)
            kind = UNKNOWN

        generation = str(payload.get("generation") or GEN1).lower()
        if generation not in _GENERATIONS:
            warnings.append("external_parser_unknown_generation=%r" % generation)
            generation = GEN1

        result = ParseResult(
            source_kind=kind,
            generation=generation,
            parser_name=self.name,
            parser_version=str(payload.get("parser_version") or self.version),
            warnings=warnings,
        )
        result.raw_evidence["external_parser"] = self.command

        card_payload = payload.get("card") or {}
        if isinstance(card_payload, dict) and card_payload:
            result.card = CardIdentification(
                issuing_member_state=card_payload.get("issuing_member_state"),
                card_number=card_payload.get("card_number"),
                driver_identification=card_payload.get("driver_identification"),
                issuing_authority=card_payload.get("issuing_authority"),
                issue_date=_parse_date(card_payload.get("issue_date"), "issue_date", warnings),
                validity_begin=_parse_date(
                    card_payload.get("validity_begin"), "validity_begin", warnings
                ),
                expiry_date=_parse_date(
                    card_payload.get("expiry_date"), "expiry_date", warnings
                ),
            )

        holder_payload = payload.get("holder") or {}
        if isinstance(holder_payload, dict) and holder_payload:
            result.holder = CardHolder(
                surname=holder_payload.get("surname"),
                first_names=holder_payload.get("first_names"),
                birth_date=_parse_date(
                    holder_payload.get("birth_date"), "birth_date", warnings
                ),
                preferred_language=holder_payload.get("preferred_language"),
            )

        vu_payload = payload.get("vehicle_unit") or {}
        if isinstance(vu_payload, dict) and vu_payload:
            result.vehicle_unit = VehicleUnitIdentification(
                serial_number=vu_payload.get("serial_number"),
                registration=vu_payload.get("registration"),
                registering_member_state=vu_payload.get("registering_member_state"),
            )

        result.days = self._to_days(payload.get("days") or [], warnings)
        return result

    @staticmethod
    def _to_days(raw_days: Any, warnings: List[str]) -> List[ActivityDay]:
        if not isinstance(raw_days, list):
            warnings.append("external_parser_days_is_not_a_list")
            return []

        days: List[ActivityDay] = []
        for index, raw_day in enumerate(raw_days):
            if not isinstance(raw_day, dict):
                warnings.append("external_parser_day_%d_is_not_an_object" % index)
                continue
            day_date = _parse_date(raw_day.get("date"), "day_%d_date" % index, warnings)
            if day_date is None:
                continue

            changes: List[ActivityChange] = []
            for raw_change in raw_day.get("changes") or []:
                if not isinstance(raw_change, dict):
                    continue
                try:
                    changes.append(
                        ActivityChange(
                            day=day_date,
                            minute_of_day=int(raw_change.get("minute", 0)),
                            activity=Activity(int(raw_change.get("activity", 0))),
                            slot=int(raw_change.get("slot", 0)),
                            crew=bool(raw_change.get("crew", False)),
                            card_not_inserted=bool(
                                raw_change.get("card_not_inserted", False)
                            ),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    warnings.append(
                        "external_parser_bad_change_in_day_%d: %s" % (index, exc)
                    )

            days.append(
                ActivityDay(
                    day=day_date,
                    presence_counter=raw_day.get("presence_counter"),
                    distance_km=raw_day.get("distance_km"),
                    changes=tuple(changes),
                )
            )
        return days
