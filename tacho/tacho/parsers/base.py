"""Parser adapter interface.

Why an interface rather than a direct dependency on a library: the well-known
Python/Go .DDD parsers carry copyleft licences (see docs/LICENCES.md), and the
one that does not — ``way-platform/tachograph-go`` (MIT) — is a Go binary, not an
importable Python package. So the service defines a narrow contract and ships two
implementations:

* ``gen1.CleanRoomGen1Parser`` — in-process, pure standard library, written from
  the regulation. Covers GEN1 **driver-card** downloads.
* ``external.ExternalCommandParser`` — shells out to any parser that reads a file
  on stdin and writes JSON on stdout. This is the documented wiring point for
  ``tachograph-go`` (MIT) and for VU downloads.

Every result carries ``warnings`` and ``unverified`` markers. Nothing in this
service is allowed to present an inferred value as a read one.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Sequence, runtime_checkable

from .errors import UnsupportedFileError
from ..domain.activities import ActivityDay

#: GEN1 is the only generation this service claims. GEN2/GEN2v2 differ in the
#: card file structure and in the download container, so parsing one with GEN1
#: offsets would produce confidently wrong driving hours. Fail closed instead.
GEN1 = "gen1"
GEN2 = "gen2"
GEN2V2 = "gen2v2"

DRIVER_CARD = "driver_card"
VEHICLE_UNIT = "vehicle_unit"
UNKNOWN = "unknown"


@dataclass
class CardHolder:
    """``DriverCardHolderIdentification`` — personal data. Handle with care."""

    surname: Optional[str] = None
    first_names: Optional[str] = None
    birth_date: Optional[_dt.date] = None
    preferred_language: Optional[str] = None

    def display_name(self) -> Optional[str]:
        parts = [p for p in (self.first_names, self.surname) if p]
        return " ".join(parts) if parts else None


@dataclass
class CardIdentification:
    """``CardIdentification`` plus the driver-card number components."""

    issuing_member_state: Optional[int] = None
    card_number: Optional[str] = None
    driver_identification: Optional[str] = None
    replacement_index: Optional[str] = None
    renewal_index: Optional[str] = None
    issuing_authority: Optional[str] = None
    issue_date: Optional[_dt.date] = None
    validity_begin: Optional[_dt.date] = None
    expiry_date: Optional[_dt.date] = None


@dataclass
class VehicleUnitIdentification:
    """VU identification, when the source file provides it."""

    serial_number: Optional[str] = None
    registration: Optional[str] = None
    registering_member_state: Optional[int] = None


@dataclass
class ParseResult:
    """The contract every parser adapter returns."""

    #: DRIVER_CARD | VEHICLE_UNIT | UNKNOWN
    source_kind: str = UNKNOWN
    #: GEN1 | GEN2 | GEN2V2
    generation: str = GEN1
    #: Version string of the parser that produced this, stored on the import row
    #: so a later re-parse can tell whether existing rows are stale.
    parser_version: str = "unknown"
    parser_name: str = "unknown"

    card: Optional[CardIdentification] = None
    holder: Optional[CardHolder] = None
    vehicle_unit: Optional[VehicleUnitIdentification] = None

    days: List[ActivityDay] = field(default_factory=list)

    #: Non-fatal problems. Every one of these is surfaced in the UI: a silently
    #: degraded parse is how a fleet ends up trusting incomplete hours.
    warnings: List[str] = field(default_factory=list)
    #: Structural facts a human can use to sanity-check the parse.
    raw_evidence: Dict[str, object] = field(default_factory=dict)

    def add_warning(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)


@runtime_checkable
class TachographParser(Protocol):
    """What a parser adapter must implement."""

    name: str
    version: str

    def supports(self, data: bytes) -> bool:
        """Cheap check: can this parser handle these bytes at all?"""
        ...

    def parse(self, data: bytes) -> ParseResult:
        """Full parse. Must raise a ``TachographError`` subclass on failure."""
        ...


class ParserRegistry:
    """Ordered list of adapters, tried in sequence.

    The clean-room parser is registered first so the common case — a GEN1 driver
    card — never depends on an external binary being installed.
    """

    def __init__(self) -> None:
        self._parsers: List[TachographParser] = []

    def register(self, parser: TachographParser) -> None:
        self._parsers.append(parser)

    @property
    def parsers(self) -> Sequence[TachographParser]:
        return tuple(self._parsers)

    def parse(self, data: bytes) -> ParseResult:
        errors: List[str] = []
        for parser in self._parsers:
            try:
                if not parser.supports(data):
                    errors.append("%s: does not recognise the file" % parser.name)
                    continue
                result = parser.parse(data)
            except UnsupportedFileError:
                # A parser that recognises the container but not the body still
                # tells the next adapter something useful, so keep going.
                errors.append("%s: recognised but unsupported" % parser.name)
                continue
            except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
                errors.append("%s: %s" % (parser.name, exc))
                continue
            if result.days or result.source_kind != UNKNOWN:
                return result
            errors.append("%s: no data extracted" % parser.name)

        if not errors:
            errors.append("no parser adapters are configured")
        raise UnsupportedFileError(
            "no configured parser could read this file (%s)" % "; ".join(errors)
        )
