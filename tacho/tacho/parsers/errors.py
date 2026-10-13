"""Parser failure taxonomy.

Every failure mode the import pipeline must survive has its own type, because
"the upload failed" is not an actionable message for a fleet manager staring at
a driver card that will not import. Malformed input is expected here: driver
cards accumulate damage, downloads get truncated, and people upload the wrong
file.

The rule for all of these: **never** let one bad file take down the worker, and
**never** write a partial activity set that looks complete.
"""

from __future__ import annotations


class TachographError(Exception):
    """Base class for every parser failure."""

    #: Short, stable, machine-readable code stored on the import row.
    code = "tachograph_error"


class UnsupportedFileError(TachographError):
    """The container is recognised but the generation/kind is not supported.

    Raised for GEN2/GEN2v2 downloads today. Failing closed here is deliberate:
    a GEN2 file parsed with GEN1 offsets would produce silently wrong driving
    hours, which is worse than an error.
    """

    code = "unsupported_file"


class NotATachographFileError(TachographError):
    """The bytes are not a tachograph download at all."""

    code = "not_a_tachograph_file"


class TruncatedFileError(TachographError):
    """A record declares more bytes than the file contains."""

    code = "truncated_file"


class MalformedRecordError(TachographError):
    """A record is present and complete but internally inconsistent."""

    code = "malformed_record"

    def __init__(self, message: str, offset: int = 0) -> None:
        super().__init__(message)
        self.offset = offset


class ParserUnavailableError(TachographError):
    """The configured external parser adapter could not be executed."""

    code = "parser_unavailable"


class ParserTimeoutError(TachographError):
    """An external parser adapter exceeded its time budget."""

    code = "parser_timeout"
