"""Synthetic GEN1 download writer, for tests and for honest fixtures.

Why this exists: you cannot lawfully distribute a real driver card, and this
service must not ship personal data in Git. So the fixtures are generated here,
byte by byte, from the same regulation the parser reads. They prove the parser is
internally consistent and that the container walking, the cyclic buffer, the
``ActivityChangeInfo`` bit layout and the day/totals arithmetic are all correct.

They do **not** prove the parser matches a real tachograph download, and no test
in this repository claims otherwise. See docs/TACHO-SERVICE.md § Verification
status.

Layout produced for a card download (Appendix 7 §3.4.2)::

    FID (2) || suffix (1) || value length (2, big-endian) || value

with ``suffix = 0x00`` for file data and ``0x01`` for that file's signature.
"""

from __future__ import annotations

import datetime as _dt
from typing import Iterable, List, Optional, Sequence, Tuple

from ..domain.activities import Activity, ActivityChange
from ..parsers.gen1 import (
    CARD_IDENTIFICATION_LEN,
    DAILY_RECORD_HEADER_LEN,
    FID_CARD_HOLDER_IDENTIFICATION,
    FID_CARD_IDENTIFICATION,
    FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT,
    FID_ICC,
    HOLDER_IDENTIFICATION_LEN,
    NAME_LEN,
    SUFFIX_DATA,
    SUFFIX_SIGNATURE,
    encode_activity_change,
)

#: Typical GEN1 driver card activity buffer size, in bytes.
DEFAULT_ACTIVITY_BUFFER_LEN = 1380

_TIME_EPOCH = _dt.datetime(1970, 1, 1, tzinfo=_dt.timezone.utc)


def encode_timereal(moment: _dt.datetime) -> bytes:
    """Encode a UTC datetime as a 4-byte ``TimeReal`` (big-endian)."""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=_dt.timezone.utc)
    seconds = int((moment - _TIME_EPOCH).total_seconds())
    if not 0 <= seconds <= 0xFFFFFFFF:
        raise ValueError("timestamp outside the TimeReal range: %s" % moment)
    return seconds.to_bytes(4, "big")


def encode_bcd(value: int, width: int) -> bytes:
    """Encode an integer as a zero-padded BCD string of ``width`` bytes."""
    text = str(value).zfill(width * 2)
    if len(text) > width * 2:
        raise ValueError("%d does not fit in %d BCD bytes" % (value, width))
    out = bytearray()
    for index in range(0, len(text), 2):
        out.append((int(text[index]) << 4) | int(text[index + 1]))
    return bytes(out)


def encode_datef(value: Optional[_dt.date]) -> bytes:
    """Encode a ``Datef``; ``None`` becomes the all-zero "no date" value.

    ``year`` is ``BCDString(SIZE(2))``: two bytes, four digits, so the full year.
    """
    if value is None:
        return b"\x00\x00\x00\x00"
    return (
        encode_bcd(value.year, 2)
        + encode_bcd(value.month, 1)
        + encode_bcd(value.day, 1)
    )


def encode_name(text: Optional[str], code_page: int = 1) -> bytes:
    """Encode a ``Name``: codePage byte plus 35 characters, NUL padded."""
    body = (text or "").encode("latin-1", errors="replace")[: NAME_LEN - 1]
    return bytes([code_page]) + body.ljust(NAME_LEN - 1, b"\x00")


def tlv(fid: int, value: bytes, suffix: int = SUFFIX_DATA) -> bytes:
    """Wrap a value in one card container object."""
    if len(value) > 0xFFFF:
        raise ValueError("value too long for a 2-byte TLV length")
    return (
        fid.to_bytes(2, "big")
        + bytes([suffix])
        + len(value).to_bytes(2, "big")
        + value
    )


class CardDownloadBuilder:
    """Assemble a synthetic GEN1 driver-card download."""

    def __init__(self, activity_buffer_len: int = DEFAULT_ACTIVITY_BUFFER_LEN) -> None:
        if activity_buffer_len < DAILY_RECORD_HEADER_LEN + 2:
            raise ValueError("activity buffer too small to hold one record")
        self.activity_buffer_len = activity_buffer_len
        self.days: List[_dt.date] = []
        self._records: List[Tuple[_dt.date, List[ActivityChange]]] = []
        self._member_state = 5  # Italy
        self._card_number = "IT0000000000001"
        self._surname = "Rossi"
        self._first_names = "Mario"
        self._birth_date = _dt.date(1980, 4, 12)
        self._authority = "Motorizzazione Civile"
        self._issue_date = _dt.date(2024, 3, 1)
        self._validity_begin = _dt.date(2024, 3, 1)
        self._expiry_date = _dt.date(2029, 3, 1)
        self.distance_km_per_day = 220
        self.presence_counter_start = 1

    # -- configuration ----------------------------------------------------
    def set_card_identity(
        self,
        card_number: str = "IT0000000000001",
        member_state: int = 5,
        authority: str = "Motorizzazione Civile",
    ) -> "CardDownloadBuilder":
        self._card_number = card_number
        self._member_state = member_state
        self._authority = authority
        return self

    def set_holder(
        self,
        surname: str = "Rossi",
        first_names: str = "Mario",
        birth_date: Optional[_dt.date] = _dt.date(1980, 4, 12),
    ) -> "CardDownloadBuilder":
        self._surname = surname
        self._first_names = first_names
        self._birth_date = birth_date
        return self

    def add_day(
        self,
        day: _dt.date,
        changes: Sequence[ActivityChange],
        distance_km: Optional[int] = None,
    ) -> "CardDownloadBuilder":
        """Add one ``CardActivityDailyRecord``.

        Changes may be given in any order; they are sorted by minute, which is
        also how the specification requires the set to be stored.
        """
        ordered = sorted(changes, key=lambda c: (c.minute_of_day, c.slot))
        if not ordered:
            raise ValueError("a daily record must contain at least one change")
        self._records.append((day, list(ordered)))
        if distance_km is not None:
            self.distance_km_per_day = distance_km
        return self

    def add_simple_day(
        self,
        day: _dt.date,
        pattern: Sequence[Tuple[int, Activity]] = ((0, Activity.BREAK_REST),),
        slot: int = 0,
    ) -> "CardDownloadBuilder":
        """Convenience: add a day from ``(minute, activity)`` pairs."""
        return self.add_day(
            day,
            [
                ActivityChange(day=day, minute_of_day=minute, activity=activity, slot=slot)
                for minute, activity in pattern
            ],
        )

    # -- serialisation ----------------------------------------------------
    def _daily_record_bytes(self, index: int, previous_length: int) -> bytes:
        day, changes = self._records[index]
        changes_bytes = b"".join(encode_activity_change(change) for change in changes)
        record_length = DAILY_RECORD_HEADER_LEN + len(changes_bytes)
        # activityRecordDate is a date-time; the date's midnight is what the
        # tachograph stores for a daily activity record.
        moment = _dt.datetime(day.year, day.month, day.day, tzinfo=_dt.timezone.utc)
        return (
            previous_length.to_bytes(2, "big")
            + record_length.to_bytes(2, "big")
            + encode_timereal(moment)
            + encode_bcd(self.presence_counter_start + index, 2)
            + min(self.distance_km_per_day, 0xFFFF).to_bytes(2, "big")
            + changes_bytes
        )

    def _build_daily_records(self) -> Tuple[bytes, int, int]:
        """Pack the daily records into the cyclic buffer.

        Returns ``(buffer, oldest_pointer, newest_pointer)``. When the records
        exceed the buffer the write wraps byte-wise, exactly as a card does, and
        the pointers describe the window that is still intact.
        """
        records: List[bytes] = []
        previous_length = 0
        for index in range(len(self._records)):
            record = self._daily_record_bytes(index, previous_length)
            previous_length = len(record)
            records.append(record)

        buffer = bytearray(self.activity_buffer_len)
        offsets: List[int] = []
        absolute = 0
        for record in records:
            start = absolute % self.activity_buffer_len
            offsets.append(start)
            for offset, byte in enumerate(record):
                buffer[(start + offset) % self.activity_buffer_len] = byte
            absolute += len(record)

        total = absolute
        intact_from = max(0, total - self.activity_buffer_len)
        keep = 0
        walked = 0
        for index, record in enumerate(records):
            if walked >= intact_from:
                keep = index
                break
            walked += len(record)

        return bytes(buffer), offsets[keep], offsets[-1]

    def build(self, include_signatures: bool = True) -> bytes:
        if not self._records:
            raise ValueError("a download must contain at least one daily record")

        parts: List[bytes] = []

        # EF ICC — identification of the card's integrated circuit. Not read by
        # the parser, but a real download always carries it, and its presence is
        # what exercises the "ignore objects you do not understand" path.
        icc = (
            b"\x01"                                 # clockStop
            + (0x12345678).to_bytes(4, "big")       # icSerialNumber
            + b"\x00\x00\x00\x00"                   # icManufacturingReferences
            + b"MOT-ICC1"[:8].ljust(8, b"\x00")     # cardApprovalNumber (8)
            + b"\x01"                               # cardPersonaliserID
            + b"\x00" * 5                           # embedderIcAssemblerId
            + b"\x00\x01"                           # icIdentifier
        )
        parts.append(tlv(FID_ICC, icc))

        # EF Card_Identification
        raw_number = (
            self._card_number.encode("ascii", errors="replace")[:14].ljust(14, b"0")
            + b"0"  # replacement index
            + b"0"  # renewal index
        )
        card_identification = (
            bytes([self._member_state])
            + raw_number
            + encode_name(self._authority)
            + encode_timereal(
                _dt.datetime.combine(self._issue_date, _dt.time(), _dt.timezone.utc)
            )
            + encode_timereal(
                _dt.datetime.combine(self._validity_begin, _dt.time(), _dt.timezone.utc)
            )
            + encode_timereal(
                _dt.datetime.combine(self._expiry_date, _dt.time(), _dt.timezone.utc)
            )
        )
        assert len(card_identification) == CARD_IDENTIFICATION_LEN
        parts.append(tlv(FID_CARD_IDENTIFICATION, card_identification))
        if include_signatures:
            parts.append(tlv(FID_CARD_IDENTIFICATION, bytes(128), SUFFIX_SIGNATURE))

        # EF Card_Holder_Identification
        holder = (
            encode_name(self._surname)
            + encode_name(self._first_names)
            + encode_datef(self._birth_date)
            + b"it"
        )
        assert len(holder) == HOLDER_IDENTIFICATION_LEN
        parts.append(tlv(FID_CARD_HOLDER_IDENTIFICATION, holder))

        # EF Driver_Activity_Daily_Records
        buffer, oldest, newest = self._build_daily_records()
        activity = oldest.to_bytes(2, "big") + newest.to_bytes(2, "big") + buffer
        parts.append(tlv(FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT, activity))
        if include_signatures:
            parts.append(
                tlv(FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT, bytes(128), SUFFIX_SIGNATURE)
            )

        return b"".join(parts)


def make_sample_card_download(
    first_day: _dt.date = _dt.date(2026, 9, 14),
    number_of_days: int = 5,
) -> bytes:
    """A deterministic, realistic-looking multi-day driver card download.

    Pattern per day: rest until 06:00, 15 minutes of other work, two hours of
    driving, a 45-minute break, three more hours of driving, then other work, then
    rest from 18:00. Deliberately includes a day whose last span is open-ended, so
    the reporting layer's handling of that is exercised too.
    """
    builder = CardDownloadBuilder()
    for index in range(number_of_days):
        day = first_day + _dt.timedelta(days=index)
        pattern: List[Tuple[int, Activity]] = [
            (0, Activity.BREAK_REST),
            (6 * 60, Activity.WORK),
            (6 * 60 + 15, Activity.DRIVING),
            (8 * 60 + 15, Activity.BREAK_REST),
            (9 * 60, Activity.DRIVING),
            (12 * 60, Activity.WORK),
            (13 * 60, Activity.DRIVING),
            (16 * 60, Activity.WORK),
            (18 * 60, Activity.BREAK_REST),
        ]
        builder.add_simple_day(day, pattern)
    return builder.build()


def make_vu_download(treps: Iterable[int] = (1, 2, 3)) -> bytes:
    """A synthetic VU stored stream: ``SID 0x76`` + one-byte TREP + placeholder.

    The bodies are placeholders on purpose. This parser refuses VU bodies, so the
    fixture exists to test *detection and refusal*, not decoding.
    """
    out = bytearray()
    for trep in treps:
        out.append(0x76)
        out.append(trep)
        out.extend(b"\xAA" * 12)
    return bytes(out)


def make_truncated_card_download(days: int = 3, keep: float = 0.5) -> bytes:
    """A valid download with its tail cut off — a real interrupted download.

    Shaped this way on purpose: a download that stops mid-object is what actually
    happens when a card is pulled out or a transfer is interrupted, and it is
    distinguishable from "this file was never a tachograph download".
    """
    full = make_sample_card_download(number_of_days=days)
    cut = int(len(full) * max(0.05, min(keep, 0.99)))
    return full[:cut]


def make_header_claiming_a_huge_length() -> bytes:
    """One object whose declared length dwarfs the whole file.

    This is what arbitrary non-tachograph bytes look like to a TLV walker: the
    first two bytes become an arbitrary "FID" and the next two an arbitrary
    length. It must be reported as "not a tachograph file", not as a truncated
    download.
    """
    value = b"\x00\x00\x00\x00" + bytes(64)
    header = FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT.to_bytes(2, "big") + b"\x00"
    return header + (len(value) + 400).to_bytes(2, "big") + value


def make_garbage() -> bytes:
    """Bytes that are not a tachograph file at all."""
    return b"this is a scanned invoice, not a tachograph download\n"
