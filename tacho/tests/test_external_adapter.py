"""Tests for the external parser adapter.

The adapter runs an operator-supplied command and trusts its JSON. That makes it a
real risk surface: it is a subprocess boundary that handles untrusted input and
returns data the rest of the system will treat as driver activity. So it gets its
own tests, driven by **stub commands** written into a temporary directory.

What these tests establish: the success path maps JSON into the domain model
correctly, and every failure mode is contained into the right exception rather than
crashing the worker or silently yielding an empty result.

What they do **not** establish: that any particular external parser exists, works, or
agrees with the clean-room parser. No real external parser is installed, so a
successful parse through `tachograph-go` remains unverified. See
docs/TACHO-SERVICE.md § Verification status.
"""

from __future__ import annotations

import datetime as _dt
import sys
import textwrap
from pathlib import Path

import pytest

from tacho.domain.activities import Activity
from tacho.parsers import (
    DRIVER_CARD,
    GEN2,
    VEHICLE_UNIT,
    ParserTimeoutError,
    ParserUnavailableError,
    UnsupportedFileError,
    default_registry,
)
from tacho.parsers.external import ExternalCommandParser


def stub(tmp_path: Path, body: str, name: str = "stub_parser.py") -> str:
    """Write a stub parser and return the command string that runs it."""
    script = tmp_path / name
    script.write_text(textwrap.dedent(body))
    return "%s %s" % (sys.executable, script)


def parser_for(tmp_path: Path, body: str, timeout: int = 30) -> ExternalCommandParser:
    return ExternalCommandParser(stub(tmp_path, body), timeout_seconds=timeout)


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

GOOD_PAYLOAD = """
    import json, sys
    sys.stdin.buffer.read()
    print(json.dumps({
        "source_kind": "vehicle_unit",
        "generation": "gen2",
        "parser_version": "tachograph-go/0.4.0",
        "card": {"card_number": "IT01234567890100", "issuing_member_state": 5,
                 "issue_date": "2024-03-01", "expiry_date": "2029-03-01"},
        "holder": {"surname": "Rossi", "first_names": "Mario",
                   "birth_date": "1980-04-12"},
        "vehicle_unit": {"serial_number": "VU-1234", "registration": "AB123CD",
                         "registering_member_state": 5},
        "days": [
            {"date": "2026-10-05", "presence_counter": 7, "distance_km": 310,
             "changes": [
                {"minute": 0, "activity": 0},
                {"minute": 390, "activity": 2},
                {"minute": 420, "activity": 3},
                {"minute": 690, "activity": 0, "card_not_inserted": True}
             ]}
        ],
        "warnings": ["sample warning"]
    }))
"""


class TestSuccessPath:
    def test_json_is_mapped_into_the_domain_model(self, tmp_path):
        result = parser_for(tmp_path, GOOD_PAYLOAD).parse(b"anything")

        assert result.source_kind == VEHICLE_UNIT
        assert result.generation == GEN2
        assert result.parser_version == "tachograph-go/0.4.0"
        assert result.parser_name.startswith("external:")

        assert result.card is not None
        assert result.card.card_number == "IT01234567890100"
        assert result.card.issue_date == _dt.date(2024, 3, 1)
        assert result.card.expiry_date == _dt.date(2029, 3, 1)

        assert result.holder is not None
        assert result.holder.surname == "Rossi"
        assert result.holder.birth_date == _dt.date(1980, 4, 12)

        assert result.vehicle_unit is not None
        assert result.vehicle_unit.registration == "AB123CD"
        assert result.vehicle_unit.serial_number == "VU-1234"

        assert len(result.days) == 1
        day = result.days[0]
        assert day.day == _dt.date(2026, 10, 5)
        assert day.presence_counter == 7
        assert day.distance_km == 310
        assert len(day.changes) == 4
        assert [change.activity for change in day.changes] == [
            Activity.BREAK_REST,
            Activity.WORK,
            Activity.DRIVING,
            Activity.BREAK_REST,
        ]
        assert day.changes[2].minute_of_day == 420
        assert day.changes[3].card_not_inserted is True
        # Every change must be anchored to the day it came from.
        assert all(change.day == _dt.date(2026, 10, 5) for change in day.changes)

        assert "sample warning" in result.warnings
        assert result.raw_evidence["external_parser"].endswith("stub_parser.py")

    def test_the_input_is_passed_on_stdin_unchanged(self, tmp_path):
        """The adapter must hand the file to the command byte-for-byte."""
        command = stub(
            tmp_path,
            """
            import hashlib, json, sys
            data = sys.stdin.buffer.read()
            print(json.dumps({"days": [], "raw": hashlib.sha256(data).hexdigest()}))
            """,
        )
        payload = bytes(range(256)) * 4
        result = ExternalCommandParser(command).parse(payload)
        assert result.source_kind == "unknown"
        assert result.days == []

    def test_stderr_is_captured_as_a_warning(self, tmp_path):
        result = parser_for(
            tmp_path,
            """
            import json, sys
            sys.stdin.buffer.read()
            print("something odd happened", file=sys.stderr)
            print(json.dumps({"days": []}))
            """,
        ).parse(b"x")
        assert any("external_parser_stderr" in warning for warning in result.warnings)

    def test_missing_optional_sections_are_tolerated(self, tmp_path):
        result = parser_for(
            tmp_path,
            """
            import json, sys
            sys.stdin.buffer.read()
            print(json.dumps({"days": [{"date": "2026-10-05", "changes": []}]}))
            """,
        ).parse(b"x")
        assert result.card is None
        assert result.holder is None
        assert result.vehicle_unit is None
        assert len(result.days) == 1
        assert result.days[0].changes == ()

    def test_an_unknown_source_kind_or_generation_is_flagged_not_trusted(self, tmp_path):
        result = parser_for(
            tmp_path,
            """
            import json, sys
            sys.stdin.buffer.read()
            print(json.dumps({"source_kind": "who_knows", "generation": "gen9",
                              "days": []}))
            """,
        ).parse(b"x")
        assert result.source_kind == "unknown"
        assert result.generation == "gen1"
        assert any("unknown_source_kind" in w for w in result.warnings)
        assert any("unknown_generation" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Malformed payloads must degrade, not crash
# ---------------------------------------------------------------------------


class TestMalformedPayloads:
    def test_a_bad_change_is_skipped_and_reported(self, tmp_path):
        result = parser_for(
            tmp_path,
            """
            import json, sys
            sys.stdin.buffer.read()
            print(json.dumps({"days": [{"date": "2026-10-05", "changes": [
                {"minute": 0, "activity": 2},
                {"minute": 60, "activity": 99},
                {"minute": 90, "activity": 3}
            ]}]}))
            """,
        ).parse(b"x")
        # The two valid changes survive; the impossible one is dropped and said so.
        assert [change.activity for change in result.days[0].changes] == [
            Activity.WORK,
            Activity.DRIVING,
        ]
        assert any("bad_change_in_day_0" in w for w in result.warnings)

    def test_an_unparsable_day_date_drops_the_day_and_warns(self, tmp_path):
        result = parser_for(
            tmp_path,
            """
            import json, sys
            sys.stdin.buffer.read()
            print(json.dumps({"days": [{"date": "not-a-date", "changes": []}]}))
            """,
        ).parse(b"x")
        assert result.days == []
        assert any("unparsable_day_0_date" in w for w in result.warnings)

    def test_days_not_being_a_list_is_reported(self, tmp_path):
        result = parser_for(
            tmp_path,
            """
            import json, sys
            sys.stdin.buffer.read()
            print(json.dumps({"days": "oops"}))
            """,
        ).parse(b"x")
        assert result.days == []
        assert any("days_is_not_a_list" in w for w in result.warnings)

    def test_an_unparsable_identification_date_is_dropped_with_a_warning(self, tmp_path):
        result = parser_for(
            tmp_path,
            """
            import json, sys
            sys.stdin.buffer.read()
            print(json.dumps({"card": {"card_number": "X", "issue_date": "soon"},
                              "days": []}))
            """,
        ).parse(b"x")
        assert result.card is not None
        assert result.card.card_number == "X"
        assert result.card.issue_date is None
        assert any("unparsable_issue_date" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Containment: every failure mode must become a typed error
# ---------------------------------------------------------------------------


class TestFailureContainment:
    def test_a_non_zero_exit_is_contained_with_the_stderr(self, tmp_path):
        parser = parser_for(
            tmp_path,
            """
            import sys
            sys.stdin.buffer.read()
            print("cannot parse GEN3 files", file=sys.stderr)
            sys.exit(3)
            """,
        )
        with pytest.raises(UnsupportedFileError) as excinfo:
            parser.parse(b"x")
        assert "exited 3" in str(excinfo.value)
        assert "cannot parse GEN3 files" in str(excinfo.value)
        assert excinfo.value.code == "unsupported_file"

    def test_invalid_json_is_contained(self, tmp_path):
        parser = parser_for(
            tmp_path,
            """
            import sys
            sys.stdin.buffer.read()
            print("this is not json")
            """,
        )
        with pytest.raises(UnsupportedFileError) as excinfo:
            parser.parse(b"x")
        assert "valid JSON" in str(excinfo.value)

    def test_json_that_is_not_an_object_is_contained(self, tmp_path):
        parser = parser_for(
            tmp_path,
            """
            import sys
            sys.stdin.buffer.read()
            print('["a list, not an object"]')
            """,
        )
        with pytest.raises(UnsupportedFileError) as excinfo:
            parser.parse(b"x")
        assert "must be an object" in str(excinfo.value)

    def test_no_output_at_all_is_contained(self, tmp_path):
        parser = parser_for(
            tmp_path,
            """
            import sys
            sys.stdin.buffer.read()
            """,
        )
        with pytest.raises(UnsupportedFileError):
            parser.parse(b"x")

    def test_a_timeout_is_contained_rather_than_hanging_the_worker(self, tmp_path):
        """A hanging external parser must not stop the worker forever."""
        parser = parser_for(
            tmp_path,
            """
            import sys, time
            sys.stdin.buffer.read()
            time.sleep(30)
            """,
            timeout=1,
        )
        with pytest.raises(ParserTimeoutError) as excinfo:
            parser.parse(b"x")
        assert "exceeded 1s" in str(excinfo.value)
        assert excinfo.value.code == "parser_timeout"

    def test_a_missing_binary_is_contained(self):
        parser = ExternalCommandParser("/nonexistent/tachograph-go-xyz parse")
        with pytest.raises(ParserUnavailableError) as excinfo:
            parser.parse(b"x")
        assert "not found" in str(excinfo.value)
        assert excinfo.value.code == "parser_unavailable"

    def test_an_empty_command_is_contained(self):
        with pytest.raises(ParserUnavailableError):
            ExternalCommandParser("   ").parse(b"x")

    def test_unbalanced_quotes_in_the_command_are_contained(self):
        with pytest.raises(ParserUnavailableError) as excinfo:
            ExternalCommandParser('parser --flag "unterminated').parse(b"x")
        assert "invalid TACHO_EXTERNAL_PARSER" in str(excinfo.value)

    def test_absurdly_large_output_is_refused(self, tmp_path):
        """An external parser must not be able to exhaust the worker's memory."""
        parser = parser_for(
            tmp_path,
            """
            import sys
            sys.stdin.buffer.read()
            sys.stdout.write("x" * (9 * 1024 * 1024))
            """,
        )
        with pytest.raises(UnsupportedFileError) as excinfo:
            parser.parse(b"x")
        assert "refusing to load it" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestRegistryIntegration:
    def test_the_adapter_claims_files_the_clean_room_parser_rejects(self, tmp_path):
        """Otherwise it would be useless for exactly the case it exists for."""
        assert ExternalCommandParser("true").supports(b"anything at all") is True

    def test_the_registry_falls_through_to_the_adapter(self, tmp_path):
        """A GEN2 file the clean-room parser cannot read must reach the adapter."""
        command = stub(
            tmp_path,
            """
            import json, sys
            sys.stdin.buffer.read()
            print(json.dumps({
                "source_kind": "driver_card", "generation": "gen2",
                "days": [{"date": "2026-10-05",
                          "changes": [{"minute": 0, "activity": 3}]}]
            }))
            """,
        )
        registry = default_registry(external_command=command)
        assert len(registry.parsers) == 2
        assert registry.parsers[0].name == "clean-room-gen1"

        result = registry.parse(b"\x00\x02\x00\x00\x63" + bytes(99))
        assert result.generation == GEN2
        assert result.source_kind == DRIVER_CARD
        assert len(result.days) == 1

    def test_no_adapter_is_registered_when_none_is_configured(self):
        registry = default_registry(external_command="")
        assert [parser.name for parser in registry.parsers] == ["clean-room-gen1"]

    def test_the_registry_failure_message_names_every_adapter(self, tmp_path):
        registry = default_registry(external_command="/nonexistent/parser")
        with pytest.raises(UnsupportedFileError) as excinfo:
            registry.parse(b"this is not a tachograph file at all")
        message = str(excinfo.value)
        # Both adapters are named, so an operator can see what was tried.
        assert "clean-room-gen1" in message
        assert "external:" in message
