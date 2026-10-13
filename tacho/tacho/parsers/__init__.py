"""Parser adapters.

``default_registry()`` returns the adapters this service uses, in order. The
clean-room GEN1 parser comes first so the ordinary case never needs an external
binary; external adapters are opt-in through configuration.
"""

from __future__ import annotations

import os
from typing import Optional

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
    ParserRegistry,
    TachographParser,
    VehicleUnitIdentification,
)
from .errors import (
    MalformedRecordError,
    NotATachographFileError,
    ParserTimeoutError,
    ParserUnavailableError,
    TachographError,
    TruncatedFileError,
    UnsupportedFileError,
)
from .gen1 import CleanRoomGen1Parser, parse_gen1

__all__ = [
    "DRIVER_CARD",
    "GEN1",
    "GEN2",
    "GEN2V2",
    "UNKNOWN",
    "VEHICLE_UNIT",
    "CardHolder",
    "CardIdentification",
    "ParseResult",
    "ParserRegistry",
    "TachographParser",
    "VehicleUnitIdentification",
    "CleanRoomGen1Parser",
    "parse_gen1",
    "default_registry",
    "TachographError",
    "UnsupportedFileError",
    "NotATachographFileError",
    "TruncatedFileError",
    "MalformedRecordError",
    "ParserUnavailableError",
    "ParserTimeoutError",
]


def default_registry(external_command: Optional[str] = None) -> ParserRegistry:
    """Build the registry used by the import worker.

    ``TACHO_EXTERNAL_PARSER`` (or the argument) names a command that reads a
    download on stdin and writes JSON on stdout. It is the supported way to add
    VU parsing or a permissively licensed third-party parser without linking it
    into this process.
    """
    registry = ParserRegistry()
    registry.register(CleanRoomGen1Parser())

    command = external_command or os.environ.get("TACHO_EXTERNAL_PARSER", "").strip()
    if command:
        from .external import ExternalCommandParser

        registry.register(ExternalCommandParser(command))
    return registry
