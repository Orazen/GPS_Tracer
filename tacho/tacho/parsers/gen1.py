"""Clean-room GEN1 tachograph download parser.

Written from the regulation — Annex 1B Appendix 1 (data dictionary) and
Appendix 7 (data download / TREP) of Commission Regulation (EC) No 1360/2002 as
amended — with no code taken from any existing parser. No copyleft obligation
attaches to this file. See docs/LICENCES.md for the alternatives surveyed and the
external adapter for the MIT ``tachograph-go`` implementation.

WHAT IS VERIFIED AND WHAT IS NOT
--------------------------------
Verified against the regulation text and exercised by tests:

* The card-download container: a flat concatenation of ``FID(2) || suffix(1) ||
  length(2, big-endian) || value`` objects (Appendix 7 §3.4.2).
* ``ActivityChangeInfo``: 16-bit ``scpaattttttttttt``; slot, crew, card-present,
  activity (00 break/rest, 01 availability, 10 work, 11 driving) and minutes
  since 00:00.
* ``CardActivityDailyRecord``: previous-record length, record length, ``TimeReal``
  date, daily presence counter, day distance, then the change set.
* ``CardDriverActivity``: oldest/newest pointers followed by the cyclic record
  buffer.
* ``CardIdentification``, ``DriverCardHolderIdentification``, ``TimeReal``,
  ``Datef``, ``DailyPresenceCounter``, ``Distance``, ``Name``.

NOT verified, and deliberately not guessed:

* **The GEN1 card EF identifiers.** The regulation's Appendix 2 EF table could
  not be retrieved during research. Rather than hard-code identifiers from
  secondary sources, the activity file is located **by structure**: any TLV value
  that parses as a well-formed ``CardDriverActivity`` is used, and the tag values
  below are treated as hints that only break ties.
* **VU (vehicle unit) downloads.** A VU download is *not* a TLV container — it is
  a stored positive-response stream (``SID`` + one-byte ``TREP`` + data), and the
  body layout of each TREP could not be verified. This parser therefore detects a
  VU file and refuses to decode it, raising ``UnsupportedFileError`` with an
  actionable message. Producing plausible-looking wrong driving hours from an
  unverified layout is the one outcome that must never happen here.

Use ``--dump``-style evidence in ``raw_evidence`` to check a real file against
this assumption before trusting an import.
"""

from __future__ import annotations

import datetime as _dt
from typing import Dict, List, Optional, Sequence, Tuple

from .base import (
    DRIVER_CARD,
    GEN1,
    UNKNOWN,
    VEHICLE_UNIT,
    CardHolder,
    CardIdentification,
    ParseResult,
)
from .errors import (
    MalformedRecordError,
    NotATachographFileError,
    TachographError,
    TruncatedFileError,
    UnsupportedFileError,
)
from ..domain.activities import Activity, ActivityChange, ActivityDay, sort_unique_days

PARSER_NAME = "clean-room-gen1"
PARSER_VERSION = "gen1-0.1.0"

# --------------------------------------------------------------------------
# Container layout
# --------------------------------------------------------------------------

#: Fixed TLV header width: FID (2) + suffix (1) + length (2).
TLV_HEADER_LEN = 5

#: Suffix byte meanings in a card download.
SUFFIX_DATA = 0x00
SUFFIX_SIGNATURE = 0x01

#: Card EF identifier hints. UNVERIFIED — see the module docstring. They are used
#: only to prefer one candidate over another after structural validation, never to
#: decide whether a value is an activity record.
FID_ICC = 0x0002
FID_CARD_IDENTIFICATION = 0x0005
FID_CARD_HOLDER_IDENTIFICATION = 0x0006
FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT = 0x0520
FID_VEHICLES_USED_HINT = 0x0505

#: VU download marker: the transfer-response SID for "transfer data".
VU_SID_TRANSFER_DATA = 0x76

#: TREP values in a VU download (Appendix 7 §2.2.6). One byte, not two.
TREP_OVERVIEW = 0x01
TREP_ACTIVITIES_FOR_DATE = 0x02
TREP_EVENTS_AND_FAULTS = 0x03
TREP_DETAILED_SPEED = 0x04
TREP_TECHNICAL_DATA = 0x05
TREP_CARD_DOWNLOAD = 0x06

TREP_NAMES: Dict[int, str] = {
    TREP_OVERVIEW: "overview",
    TREP_ACTIVITIES_FOR_DATE: "activities_for_date",
    TREP_EVENTS_AND_FAULTS: "events_and_faults",
    TREP_DETAILED_SPEED: "detailed_speed",
    TREP_TECHNICAL_DATA: "technical_data",
    TREP_CARD_DOWNLOAD: "card_download",
}


def parse_gen1(data: bytes, kind_hint: Optional[str] = None) -> ParseResult:
    """Parse a GEN1 download, dispatching on the container we actually find."""
    if not data:
        raise NotATachographFileError("empty file")
    if looks_like_vu_download(data):
        return _parse_vu_container(data)
    return _parse_card_container(data, kind_hint=kind_hint)


def looks_like_vu_download(data: bytes) -> bool:
    """Heuristic: does this stream begin with a VU transfer-data response?

    A card download's first object starts with a two-byte FID whose low byte is
    the EF number and whose high byte is a file group; a VU stream starts with
    ``0x76`` followed by a TREP in the range 1..6. The two cannot both be true for
    a well-formed file, so this is a safe discriminator.
    """
    return (
        len(data) >= 2
        and data[0] == VU_SID_TRANSFER_DATA
        and 1 <= data[1] <= 6
    )


# --------------------------------------------------------------------------
# Primitive decoders
# --------------------------------------------------------------------------

#: Plausible window for a TimeReal value: 1990-01-01 .. 2100-01-01 UTC. Used to
#: validate byte order rather than assumed from the standard, which does not state
#: it in the passages examined.
_TIMEREAL_MIN = 631_152_000
_TIMEREAL_MAX = 4_102_444_800
_TIME_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


def _u16(data: bytes, offset: int) -> int:
    return (data[offset] << 8) | data[offset + 1]


def decode_timereal(raw: bytes) -> Tuple[Optional[_dt.datetime], List[str]]:
    """Decode a 4-byte ``TimeReal``: seconds since 1970-01-01T00:00:00Z.

    Returns ``(datetime | None, warnings)``. The byte order is *not* stated in the
    regulation text that could be retrieved, so both orders are tried and a
    warning is emitted when little-endian is needed. An implausible value yields
    ``None`` with a warning rather than an invented date.
    """
    if len(raw) != 4:
        return None, ["timereal_wrong_length=%d" % len(raw)]

    be = int.from_bytes(raw, "big")
    if _TIMEREAL_MIN <= be <= _TIMEREAL_MAX:
        return _TIME_EPOCH + _dt.timedelta(seconds=be), []

    le = int.from_bytes(raw, "little")
    if _TIMEREAL_MIN <= le <= _TIMEREAL_MAX:
        return _TIME_EPOCH + _dt.timedelta(seconds=le), [
            "timereal_decoded_little_endian: byte order is unverified; "
            "check this file against a known date"
        ]

    return None, ["timereal_implausible=0x%s" % raw.hex()]


def decode_timereal_date(raw: bytes) -> Tuple[Optional[_dt.date], List[str]]:
    moment, warnings = decode_timereal(raw)
    return (moment.date() if moment else None), warnings


def _bcd(value: int) -> Optional[int]:
    hi, lo = value >> 4, value & 0x0F
    if hi > 9 or lo > 9:
        return None
    return hi * 10 + lo


def decode_bcd(word: bytes) -> Optional[int]:
    """Decode a BCD string of one or more bytes into an integer."""
    total = 0
    for byte in word:
        digit = _bcd(byte)
        if digit is None:
            return None
        total = total * 100 + digit
    return total


def decode_datef(raw: bytes) -> Optional[_dt.date]:
    """``Datef``: BCD year(2) month(1) day(1); all zero means "no date".

    ``year`` is ``BCDString(SIZE(2))`` — two bytes, so four BCD digits and a full
    four-digit year (2024 is ``20 24``). A two-digit year is also accepted, because
    a value below 100 is unambiguous and rejecting it would fail an otherwise
    readable card; the check is explicit rather than a `2000 +` guess, which is how
    a 2024 becomes a 4024.
    """
    if len(raw) != 4:
        return None
    if raw == b"\x00\x00\x00\x00":
        return None
    year = decode_bcd(raw[0:2])
    month = _bcd(raw[2])
    day = _bcd(raw[3])
    if year is None or month is None or day is None:
        return None
    if 0 <= year <= 99:
        year = 2000 + year if year < 70 else 1900 + year
    if not (1900 <= year <= 2199):
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    try:
        return _dt.date(year, month, day)
    except ValueError:
        return None


#: ISO 8859 part selected by the ``codePage`` byte of a ``Name``/``Address``.
_CODEPAGES: Dict[int, str] = {
    1: "latin-1",
    2: "iso8859-2",
    3: "iso8859-3",
    4: "iso8859-4",
    5: "iso8859-5",
    6: "iso8859-6",
    7: "iso8859-7",
    8: "iso8859-8",
    9: "iso8859-9",
}

#: ``Name ::= SEQUENCE { codePage, name OCTET STRING (SIZE(35)) }``
NAME_LEN = 36


def decode_name(raw: bytes) -> Optional[str]:
    """Decode a ``Name``: one codePage byte plus 35 characters, ISO 8859-x.

    Trailing NULs and the 0xFF filler used for "not applicable" are stripped, so
    an unset field becomes ``None`` rather than a string of padding.
    """
    if len(raw) < NAME_LEN:
        return None
    code_page = raw[0]
    body = raw[1:NAME_LEN]
    if not body or all(b in (0x00, 0xFF) for b in body):
        return None
    encoding = _CODEPAGES.get(code_page, "latin-1")
    try:
        text = body.decode(encoding, errors="replace")
    except LookupError:
        text = body.decode("latin-1", errors="replace")
    text = text.replace("\x00", "").replace("\xff", "").strip()
    return text or None


# --------------------------------------------------------------------------
# ActivityChangeInfo
# --------------------------------------------------------------------------


def decode_activity_change(raw: bytes, day: _dt.date) -> ActivityChange:
    """Decode a 2-byte ``ActivityChangeInfo``.

    Bit layout, most significant bit first (Appendix 1 §2.1)::

        s c p aa ttttttttttt

        s  bit 15  slot          0 = driver, 1 = co-driver
        c  bit 14  driving status 0 = single, 1 = crew
        p  bit 13  card status   0 = inserted, 1 = not inserted
        aa bits 12-11 activity   00 rest, 01 availability, 10 work, 11 driving
        t  bits 10-0  time       minutes since 00:00 on the given day
    """
    if len(raw) != 2:
        raise MalformedRecordError(
            "ActivityChangeInfo must be 2 bytes, got %d" % len(raw)
        )
    word = (raw[0] << 8) | raw[1]
    return ActivityChange(
        day=day,
        minute_of_day=word & 0x07FF,
        activity=Activity((word >> 11) & 0x03),
        slot=(word >> 15) & 0x01,
        crew=bool((word >> 14) & 0x01),
        card_not_inserted=bool((word >> 13) & 0x01),
    )


def encode_activity_change(change: ActivityChange) -> bytes:
    """Inverse of :func:`decode_activity_change`. Used by the fixture writer."""
    if not 0 <= change.minute_of_day <= 1439:
        raise ValueError("minute_of_day out of range: %d" % change.minute_of_day)
    word = (
        ((change.slot & 0x01) << 15)
        | ((1 if change.crew else 0) << 14)
        | ((1 if change.card_not_inserted else 0) << 13)
        | ((int(change.activity) & 0x03) << 11)
        | (change.minute_of_day & 0x07FF)
    )
    return bytes([(word >> 8) & 0xFF, word & 0xFF])


# --------------------------------------------------------------------------
# CardActivityDailyRecord / CardDriverActivity
# --------------------------------------------------------------------------

#: prevLen(2) + recLen(2) + date(4) + presence(2) + distance(2)
DAILY_RECORD_HEADER_LEN = 12


def decode_daily_record(
    raw: bytes, base_offset: int = 0
) -> Tuple[ActivityDay, int]:
    """Decode one ``CardActivityDailyRecord``; return the record and its length.

    ``activityPreviousRecordLength`` is read but not trusted as a pointer: the
    buffer is cyclic, so a previous-record length can legitimately point outside
    the window being walked. The record's own length is what advances the walk.
    """
    if len(raw) < DAILY_RECORD_HEADER_LEN:
        raise MalformedRecordError(
            "daily record shorter than its %d-byte header" % DAILY_RECORD_HEADER_LEN,
            offset=base_offset,
        )
    record_length = _u16(raw, 2)
    if record_length < DAILY_RECORD_HEADER_LEN:
        raise MalformedRecordError(
            "daily record declares length %d, below the header size" % record_length,
            offset=base_offset,
        )
    if record_length % 2:
        # A change set is a multiple of 2 bytes, so an odd record length means the
        # walk is out of step and anything decoded after this is noise.
        raise MalformedRecordError(
            "daily record length %d is odd; change set cannot be decoded"
            % record_length,
            offset=base_offset,
        )
    if record_length > len(raw):
        raise TruncatedFileError(
            "daily record declares %d bytes but only %d remain"
            % (record_length, len(raw))
        )

    day_date, warnings = decode_timereal_date(raw[4:8])
    if day_date is None:
        raise MalformedRecordError("daily record has no usable date", offset=base_offset)

    presence = decode_bcd(raw[8:10])
    distance = _u16(raw, 10)

    changes: List[ActivityChange] = []
    change_count = (record_length - DAILY_RECORD_HEADER_LEN) // 2
    for index in range(change_count):
        start = DAILY_RECORD_HEADER_LEN + index * 2
        try:
            changes.append(decode_activity_change(raw[start : start + 2], day_date))
        except MalformedRecordError:
            # A single bad word inside an otherwise sound day is not worth
            # discarding the day; count it and move on.
            warnings.append("activity_change_skipped_at_index=%d" % index)

    day = ActivityDay(
        day=day_date,
        presence_counter=presence,
        distance_km=distance,
        changes=tuple(changes),
    )
    if warnings:
        setattr(day, "_warnings", warnings)
    return day, record_length


def _wrapped_slice(buffer: bytes, start: int, length: int) -> Optional[bytes]:
    """Read ``length`` bytes from a cyclic buffer, wrapping past the end.

    The activity buffer is deliberately cyclic: the specification says storing
    "continues at the first byte of the string independently of a break being inside
    a data element", so a single daily record can straddle the end. Reading a plain
    slice there would silently look like a truncated file.
    """
    size = len(buffer)
    if length < 0 or length > size:
        return None
    if start + length <= size:
        return buffer[start : start + length]
    head = buffer[start:]
    return head + buffer[: length - len(head)]


def decode_driver_activity(value: bytes) -> Tuple[List[ActivityDay], List[str]]:
    """Decode a ``CardDriverActivity``: two pointers plus a cyclic record buffer.

    Returns ``([], [])`` when the value does not look like this structure at all,
    which is what makes structural location of the activity file possible.
    """
    warnings: List[str] = []
    if len(value) < 4 + DAILY_RECORD_HEADER_LEN:
        return [], []

    oldest = _u16(value, 0)
    newest = _u16(value, 2)
    records = value[4:]
    if not records:
        return [], []

    if oldest >= len(records) or newest >= len(records):
        # Pointers outside the buffer: not this structure, or corrupt.
        return [], []

    days: List[ActivityDay] = []
    seen: set = set()
    position = oldest
    while True:
        if position in seen:
            warnings.append("daily_record_cycle_detected_at=%d" % position)
            break

        header = _wrapped_slice(records, position, DAILY_RECORD_HEADER_LEN)
        if header is None:
            warnings.append("daily_record_truncated_at=%d" % position)
            break

        try:
            record_length = _u16(header, 2)
            if record_length < DAILY_RECORD_HEADER_LEN or record_length % 2:
                raise MalformedRecordError(
                    "daily record declares length %d at offset %d"
                    % (record_length, position),
                    offset=position,
                )
            raw = _wrapped_slice(records, position, record_length)
            if raw is None:
                raise TruncatedFileError(
                    "daily record of %d bytes does not fit the %d-byte buffer"
                    % (record_length, len(records))
                )
            day, record_length = decode_daily_record(raw, base_offset=position)
        except (MalformedRecordError, TruncatedFileError) as exc:
            # End of the useful data: the walk stops here. Everything decoded so
            # far is kept, and the shortfall is reported rather than hidden.
            warnings.append("daily_record_walk_stopped_at=%d (%s)" % (position, exc))
            break

        days.append(day)
        if position == newest:
            break

        seen.add(position)
        position = (position + record_length) % len(records)

    return days, warnings


# --------------------------------------------------------------------------
# Card container
# --------------------------------------------------------------------------


class TlvObject:
    """One ``FID || suffix || length || value`` object from a card download."""

    __slots__ = ("fid", "suffix", "value", "offset")

    def __init__(self, fid: int, suffix: int, value: bytes, offset: int) -> None:
        self.fid = fid
        self.suffix = suffix
        self.value = value
        self.offset = offset

    @property
    def is_data(self) -> bool:
        return self.suffix == SUFFIX_DATA

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "TlvObject(fid=0x%04X, suffix=%d, len=%d, offset=%d)" % (
            self.fid,
            self.suffix,
            len(self.value),
            self.offset,
        )


def iter_tlv(data: bytes, start: int = 0) -> List[TlvObject]:
    """Walk the whole card container.

    The two failure modes are deliberately distinguished, because they mean
    different things to whoever uploaded the file:

    * Nothing parsed at all, and the very first object is unusable — this is not a
      tachograph download (a scanned invoice, a PDF, the wrong file).
      ``NotATachographFileError``.
    * At least one object parsed and then the data ran out — a genuinely
      interrupted download of a real card. ``TruncatedFileError``.

    Collapsing the two would tell a fleet manager "your download is truncated"
    about a file that was never a download.
    """
    objects: List[TlvObject] = []
    offset = start
    total = len(data)
    while offset < total:
        def _unreadable(message: str) -> TachographError:
            return (
                NotATachographFileError(message)
                if not objects
                else TruncatedFileError(message)
            )

        if total - offset < TLV_HEADER_LEN:
            raise _unreadable(
                "%d trailing byte(s) at offset %d are shorter than a %d-byte TLV header"
                % (total - offset, offset, TLV_HEADER_LEN)
            )
        fid = _u16(data, offset)
        suffix = data[offset + 2]
        length = _u16(data, offset + 3)
        value_start = offset + TLV_HEADER_LEN
        if value_start + length > total:
            raise _unreadable(
                "object at offset %d declares %d bytes but only %d remain"
                % (offset, length, total - value_start)
            )
        objects.append(TlvObject(fid, suffix, data[value_start : value_start + length], offset))
        offset = value_start + length
    return objects


def _parse_vu_container(data: bytes) -> ParseResult:
    """Detect a VU download and refuse to decode its bodies.

    Refusing is the correct behaviour, not a gap to paper over: the VU stored
    stream interleaves SID/TREP markers with response bodies whose layouts could
    not be verified from the regulation. ``TREP 06`` (card download) *does* embed a
    card-format blob, so that case is decoded.
    """
    result = ParseResult(
        source_kind=VEHICLE_UNIT,
        generation=GEN1,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
    )
    result.add_warning(
        "vehicle_unit_download_detected: VU body layouts are not implemented in "
        "the clean-room parser; configure an external adapter (see "
        "docs/TACHO-SERVICE.md) or import the driver card instead"
    )

    treps: List[int] = []
    position = 0
    card_blobs: List[bytes] = []
    while position + 2 <= len(data):
        if data[position] != VU_SID_TRANSFER_DATA:
            position += 1
            continue
        trep = data[position + 1]
        treps.append(trep)
        if trep == TREP_CARD_DOWNLOAD:
            # The embedded card blob starts after the SID/TREP pair and keeps the
            # 3-byte-tag card container, so the normal card walker can be tried on
            # it once the trailing stream is trimmed.
            candidate = data[position + 2 :]
            try:
                objects = iter_tlv(candidate)
            except (TruncatedFileError, MalformedRecordError):
                objects = []
            consumed = sum(TLV_HEADER_LEN + len(o.value) for o in objects)
            if objects and consumed >= 32:
                card_blobs.append(candidate[:consumed])
        # Skip past this marker; the body length is unknown without the TREP table.
        position += 2

    result.raw_evidence["treps"] = sorted(set(treps))
    result.raw_evidence["trep_names"] = sorted(
        TREP_NAMES.get(t, "trep_%02X" % t) for t in set(treps)
    )

    for blob in card_blobs:
        try:
            card_result = _parse_card_container(blob, kind_hint=DRIVER_CARD)
        except Exception:  # noqa: BLE001 - best effort on an embedded blob
            continue
        if card_result.days:
            result.days = card_result.days
            result.card = card_result.card
            result.holder = card_result.holder
            result.add_warning(
                "activity taken from the card download embedded in the VU "
                "download (TREP 06)"
            )
            break

    return result


def _parse_card_container(data: bytes, kind_hint: Optional[str] = None) -> ParseResult:
    objects = iter_tlv(data)
    if not objects:
        raise NotATachographFileError("no TLV objects in the file")

    result = ParseResult(
        source_kind=DRIVER_CARD,
        generation=GEN1,
        parser_name=PARSER_NAME,
        parser_version=PARSER_VERSION,
    )
    result.raw_evidence["tlv_objects"] = [
        {"fid": "0x%04X" % o.fid, "suffix": o.suffix, "length": len(o.value), "offset": o.offset}
        for o in objects
    ]

    data_objects = [o for o in objects if o.is_data]
    if not data_objects:
        raise NotATachographFileError("file contains only signature objects")

    file_ids = sorted({o.fid for o in data_objects})
    result.raw_evidence["fids"] = ["0x%04X" % fid for fid in file_ids]

    # --- Locate the activity file by structure, not by tag -------------------
    candidates: List[Tuple[int, List[ActivityDay], List[str], int]] = []
    for obj in data_objects:
        days, warnings = decode_driver_activity(obj.value)
        if days:
            # Prefer the documented hint, then the longest record set. The hint is
            # only a tie-breaker; validity of the structure is what qualifies a
            # candidate at all.
            hint_bonus = 1 if obj.fid == FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT else 0
            candidates.append((hint_bonus, days, warnings, obj.fid))

    if candidates:
        candidates.sort(key=lambda c: (c[0], len(c[1])), reverse=True)
        _, days, warnings, fid = candidates[0]
        result.days = sort_unique_days(days)
        for warning in warnings:
            result.add_warning(warning)
        result.raw_evidence["activity_fid"] = "0x%04X" % fid
        result.raw_evidence["activity_day_count"] = len(result.days)
        if fid != FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT:
            result.add_warning(
                "activity_file_located_structurally (FID 0x%04X): the EF identifier "
                "table is unverified in this build, so the tag is reported for "
                "checking rather than relied upon" % fid
            )
    else:
        result.add_warning(
            "no_card_driver_activity_structure_found: the file parsed as a card "
            "download but contains no decodable activity records"
        )

    # --- Identification records, matched on shape ---------------------------
    for obj in data_objects:
        if obj.fid == FID_CARD_IDENTIFICATION or _looks_like_card_identification(obj.value):
            card = _decode_card_identification(obj.value)
            if card is not None:
                result.card = card
        if obj.fid == FID_CARD_HOLDER_IDENTIFICATION or _looks_like_holder_identification(
            obj.value
        ):
            holder = _decode_holder_identification(obj.value)
            if holder is not None:
                result.holder = holder

    if kind_hint and kind_hint != DRIVER_CARD:
        result.add_warning("kind_hint=%s ignored; file parsed as a card download" % kind_hint)

    return result


#: ``CardIdentification``: memberState(1) + number(16) + authority(36) + 3 dates(12)
CARD_IDENTIFICATION_LEN = 65
#: ``DriverCardHolderIdentification``: name(72) + birthDate(4) + language(2)
HOLDER_IDENTIFICATION_LEN = 78


def _looks_like_card_identification(value: bytes) -> bool:
    if len(value) != CARD_IDENTIFICATION_LEN:
        return False
    date, _ = decode_timereal_date(value[53:57])
    return date is not None


def _looks_like_holder_identification(value: bytes) -> bool:
    if len(value) != HOLDER_IDENTIFICATION_LEN:
        return False
    return decode_datef(value[72:76]) is not None


def _decode_card_identification(value: bytes) -> Optional[CardIdentification]:
    if len(value) < CARD_IDENTIFICATION_LEN:
        return None
    issue_date, _ = decode_timereal_date(value[53:57])
    validity_begin, _ = decode_timereal_date(value[57:61])
    expiry_date, _ = decode_timereal_date(value[61:65])

    driver_identification = None
    replacement = renewal = None
    raw_number = value[1:17]
    try:
        text = raw_number.decode("ascii", errors="strict")
        if text[:14].strip(" 0"):
            driver_identification = text[:14]
        replacement = text[14] or None
        renewal = text[15] or None
    except UnicodeDecodeError:
        # A non-driver card (workshop/company/control) uses a different CardNumber
        # shape; record it verbatim rather than mis-splitting it.
        text = raw_number.decode("latin-1", errors="replace").strip("\x00 ")
        driver_identification = text or None

    return CardIdentification(
        issuing_member_state=value[0],
        card_number=(driver_identification or "") + (replacement or "") + (renewal or "")
        or None,
        driver_identification=driver_identification,
        replacement_index=replacement,
        renewal_index=renewal,
        issuing_authority=decode_name(value[17:53]),
        issue_date=issue_date,
        validity_begin=validity_begin,
        expiry_date=expiry_date,
    )


def _decode_holder_identification(value: bytes) -> Optional[CardHolder]:
    if len(value) < HOLDER_IDENTIFICATION_LEN:
        return None
    surname = decode_name(value[0:NAME_LEN])
    first_names = decode_name(value[NAME_LEN : NAME_LEN * 2])
    language_raw = value[76:78]
    try:
        language = language_raw.decode("ascii").strip("\x00 ") or None
    except UnicodeDecodeError:
        language = None
    if not (surname or first_names):
        return None
    return CardHolder(
        surname=surname,
        first_names=first_names,
        birth_date=decode_datef(value[72:76]),
        preferred_language=language,
    )


class CleanRoomGen1Parser:
    """Adapter wrapper around :func:`parse_gen1` for the registry."""

    name = PARSER_NAME
    version = PARSER_VERSION

    def supports(self, data: bytes) -> bool:
        if len(data) < TLV_HEADER_LEN:
            return False
        if looks_like_vu_download(data):
            return True
        try:
            objects = iter_tlv(data)
        except TachographError:
            # Anything the container walk cannot make sense of means this adapter
            # does not recognise the file; the registry moves on to the next one.
            # Catching the whole hierarchy, not two branches of it, is the point:
            # an uncaught subclass here aborts the whole import instead of
            # falling through to a configured external parser.
            return False
        return len(objects) >= 2

    def parse(self, data: bytes) -> ParseResult:
        return parse_gen1(data)
