"""Tests for the clean-room GEN1 parser and the synthetic fixture writer.

Two distinct claims are being tested, and it matters which is which:

1. **Internal consistency** — the writer and the parser agree, the container walk
   is correct, the cyclic buffer wraps correctly, and the bit layout round-trips.
   These tests are strong evidence for all of that.
2. **Third-party interoperability** — that the parser reads a *real* tachograph
   download. **No test here establishes that**, because no lawful real sample is
   available. See docs/TACHO-SERVICE.md § Verification status.

Read the assertions with that distinction in mind.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from tacho.domain.activities import Activity, ActivityChange, summarise_day
from tacho.fixtures.gen1_writer import (
    CardDownloadBuilder,
    encode_activity_change,
    make_garbage,
    make_header_claiming_a_huge_length,
    make_sample_card_download,
    make_truncated_card_download,
    make_vu_download,
)
from tacho.parsers import (
    DRIVER_CARD,
    VEHICLE_UNIT,
    NotATachographFileError,
    TruncatedFileError,
    UnsupportedFileError,
    default_registry,
    parse_gen1,
)
from tacho.parsers.gen1 import (
    FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT,
    CleanRoomGen1Parser,
    decode_activity_change,
    decode_datef,
    decode_name,
    decode_timereal,
    iter_tlv,
)

DAY = _dt.date(2026, 9, 14)


# ---------------------------------------------------------------------------
# ActivityChangeInfo bit layout
# ---------------------------------------------------------------------------


class TestActivityChangeBits:
    """The bit layout is quoted verbatim in the module docstring; pin it down."""

    @pytest.mark.parametrize("minute", [0, 1, 359, 719, 1103, 1439])
    @pytest.mark.parametrize("activity", list(Activity))
    @pytest.mark.parametrize("slot", [0, 1])
    @pytest.mark.parametrize("crew", [False, True])
    @pytest.mark.parametrize("card_not_inserted", [False, True])
    def test_round_trip(self, minute, activity, slot, crew, card_not_inserted):
        change = ActivityChange(
            day=DAY,
            minute_of_day=minute,
            activity=activity,
            slot=slot,
            crew=crew,
            card_not_inserted=card_not_inserted,
        )
        decoded = decode_activity_change(encode_activity_change(change), DAY)
        assert decoded == change

    def test_known_bit_patterns(self):
        """Hand-computed words from the documented layout.

        ``s c p aa ttttttttttt`` with ``s`` at bit 15 and the time in bits 10-0.
        """
        # Driver slot, single, card inserted, DRIVING (11), minute 375 (06:15).
        word = (0 << 15) | (0 << 14) | (0 << 13) | (0b11 << 11) | 375
        assert word == 0x1977
        decoded = decode_activity_change(word.to_bytes(2, "big"), DAY)
        assert decoded.activity is Activity.DRIVING
        assert decoded.minute_of_day == 375
        assert decoded.slot == 0
        assert not decoded.crew
        assert not decoded.card_not_inserted

        # Co-driver, crew, card NOT inserted, BREAK/REST (00), minute 0.
        word = (1 << 15) | (1 << 14) | (1 << 13) | (0b00 << 11) | 0
        assert word == 0xE000
        decoded = decode_activity_change(word.to_bytes(2, "big"), DAY)
        assert decoded.activity is Activity.BREAK_REST
        assert decoded.slot == 1
        assert decoded.crew
        assert decoded.card_not_inserted

    def test_activity_codes_follow_the_regulation(self):
        """aa: 00 rest, 01 availability, 10 work, 11 driving."""
        for code, expected in (
            (0b00, Activity.BREAK_REST),
            (0b01, Activity.AVAILABILITY),
            (0b10, Activity.WORK),
            (0b11, Activity.DRIVING),
        ):
            decoded = decode_activity_change(bytes([code << 3, 0]), DAY)
            assert decoded.activity is expected

    def test_rejects_wrong_width(self):
        with pytest.raises(Exception):
            decode_activity_change(b"\x00", DAY)

    def test_encode_rejects_out_of_range_minute(self):
        with pytest.raises(ValueError):
            encode_activity_change(
                ActivityChange(day=DAY, minute_of_day=1440, activity=Activity.WORK)
            )


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


class TestPrimitives:
    def test_timereal_big_endian(self):
        raw = (1_700_000_000).to_bytes(4, "big")
        moment, warnings = decode_timereal(raw)
        assert moment == _dt.datetime(2023, 11, 14, 22, 13, 20, tzinfo=_dt.timezone.utc)
        assert warnings == []

    def test_timereal_reports_little_endian_rather_than_guessing(self):
        raw = (1_700_000_000).to_bytes(4, "little")
        moment, warnings = decode_timereal(raw)
        assert moment is not None
        assert any("little_endian" in w for w in warnings)

    def test_timereal_implausible(self):
        moment, warnings = decode_timereal(b"\x00\x00\x00\x01")
        assert moment is None
        assert any("implausible" in w for w in warnings)

    def test_datef_uses_a_two_byte_year(self):
        """``year`` is BCDString(SIZE(2)): four digits, so 20 24 for 2024."""
        assert decode_datef(bytes.fromhex("2024") + bytes([3]) + bytes([1])) == _dt.date(
            2024, 3, 1
        )
        assert decode_datef(b"\x00\x00\x00\x00") is None
        # A 2-digit year stays unambiguous rather than becoming 2000 + 24 = 2024
        # by accident of a different interpretation.
        assert decode_datef(bytes.fromhex("0024") + bytes([3]) + bytes([1])) == _dt.date(
            2024, 3, 1
        )
        # 0x0A is not valid BCD and must not be accepted.
        assert decode_datef(bytes.fromhex("200A") + bytes([3]) + bytes([1])) is None
        # An implausible year is refused instead of silently shifted.
        assert decode_datef(bytes.fromhex("9900") + bytes([3]) + bytes([1])) is None

    def test_datef_round_trips_through_the_writer(self):
        from tacho.fixtures.gen1_writer import encode_datef

        for day in (
            _dt.date(2024, 3, 1),
            _dt.date(1980, 4, 12),
            _dt.date(2029, 3, 1),
            _dt.date(2026, 12, 31),
        ):
            assert decode_datef(encode_datef(day)) == day

    def test_name_strips_filler(self):
        assert decode_name(bytes([1]) + b"Rossi".ljust(35, b"\x00")) == "Rossi"
        assert decode_name(bytes([1]) + b"\xff" * 35) is None
        assert decode_name(bytes([1]) + b"Citt\xe0".ljust(35, b"\x00")) == "Citt\xe0"


# ---------------------------------------------------------------------------
# Container and round trip
# ---------------------------------------------------------------------------


class TestContainer:
    def test_tlv_walk(self):
        data = make_sample_card_download(number_of_days=1)
        objects = iter_tlv(data)
        assert len(objects) >= 4
        # Every object's declared length must exactly account for the file.
        consumed = sum(5 + len(o.value) for o in objects)
        assert consumed == len(data)

    def test_interrupted_download_is_reported_as_truncated(self):
        """A real truncation: some objects parsed, then the data ran out."""
        with pytest.raises(TruncatedFileError):
            iter_tlv(make_truncated_card_download())

    def test_garbage_is_not_a_tachograph_file(self):
        """Nothing parsed, so the file was never a download.

        The distinction matters: reporting "your download is truncated" about a
        scanned invoice sends the user looking for the wrong problem.
        """
        parser = CleanRoomGen1Parser()
        assert parser.supports(make_garbage()) is False
        with pytest.raises(NotATachographFileError):
            parser.parse(make_garbage())
        with pytest.raises(NotATachographFileError):
            parser.parse(make_header_claiming_a_huge_length())

    def test_an_empty_file_is_not_a_tachograph_file(self):
        with pytest.raises(NotATachographFileError):
            CleanRoomGen1Parser().parse(b"")


class TestCardRoundTrip:
    def test_sample_download_parses(self):
        result = parse_gen1(make_sample_card_download(number_of_days=5))

        assert result.source_kind == DRIVER_CARD
        assert result.generation == "gen1"
        assert result.parser_name == "clean-room-gen1"
        assert len(result.days) == 5
        # Located structurally, and the tag happened to match the hint.
        assert result.raw_evidence["activity_fid"] == "0x%04X" % (
            FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT
        )

    def test_identification_records_are_decoded(self):
        result = parse_gen1(make_sample_card_download(number_of_days=1))

        assert result.holder is not None
        assert result.holder.surname == "Rossi"
        assert result.holder.first_names == "Mario"
        assert result.holder.birth_date == _dt.date(1980, 4, 12)
        assert result.holder.display_name() == "Mario Rossi"

        assert result.card is not None
        assert result.card.issuing_member_state == 5
        assert result.card.driver_identification == "IT000000000000"
        assert result.card.issue_date == _dt.date(2024, 3, 1)
        assert result.card.expiry_date == _dt.date(2029, 3, 1)

    def test_day_totals_are_exact(self):
        result = parse_gen1(make_sample_card_download(number_of_days=1))
        totals = summarise_day(result.days[0])

        assert totals.minutes_of(Activity.DRIVING) == 480
        assert totals.minutes_of(Activity.WORK) == 195
        assert totals.minutes_of(Activity.BREAK_REST) == 765
        assert totals.minutes_of(Activity.AVAILABILITY) == 0
        # The day is fully accounted for, so nothing is "unknown".
        assert totals.uncovered_minutes == 0
        assert totals.total_recorded + totals.uncovered_minutes == 24 * 60

    def test_card_number_is_split_into_its_components(self):
        """``driverIdentification`` is 14 characters, then the two indices."""
        builder = CardDownloadBuilder().set_card_identity(card_number="IT012345678901")
        builder.add_simple_day(DAY, [(0, Activity.DRIVING), (60, Activity.BREAK_REST)])
        result = parse_gen1(builder.build())
        assert result.card is not None
        assert result.card.driver_identification == "IT012345678901"
        assert result.card.replacement_index == "0"
        assert result.card.renewal_index == "0"
        # A short identification is padded, not silently mis-split.
        short = CardDownloadBuilder().set_card_identity(card_number="IT1")
        short.add_simple_day(DAY, [(0, Activity.WORK), (60, Activity.BREAK_REST)])
        assert parse_gen1(short.build()).card.driver_identification == "IT100000000000"

    def test_no_identification_records_is_not_a_failure(self):
        """A download may legitimately carry only activity."""
        builder = CardDownloadBuilder()
        builder.add_simple_day(DAY, [(0, Activity.WORK), (60, Activity.BREAK_REST)])
        data = builder.build()
        result = parse_gen1(data)
        assert len(result.days) == 1


class TestCyclicBuffer:
    def test_records_that_fit_do_not_wrap(self):
        builder = CardDownloadBuilder(activity_buffer_len=200)
        for index in range(3):
            builder.add_simple_day(
                DAY + _dt.timedelta(days=index),
                [(0, Activity.WORK), (60, Activity.DRIVING), (120, Activity.BREAK_REST)],
            )
        result = parse_gen1(builder.build())
        assert [d.day for d in result.days] == [
            DAY,
            DAY + _dt.timedelta(days=1),
            DAY + _dt.timedelta(days=2),
        ]

    def test_a_record_may_straddle_the_end_of_the_buffer(self):
        """The buffer is cyclic: one record can wrap across the boundary.

        This is the case that a naive slice-reads-the-file implementation gets
        wrong, reporting a healthy file as truncated.
        """
        # One day: 12-byte header + 3 changes = 18 bytes. A 30-byte buffer holds
        # one record and can only fit a second by wrapping through the boundary.
        builder = CardDownloadBuilder(activity_buffer_len=30)
        for index in range(2):
            builder.add_simple_day(
                DAY + _dt.timedelta(days=index),
                [(0, Activity.WORK), (60, Activity.DRIVING), (120, Activity.BREAK_REST)],
            )
        result = parse_gen1(builder.build())
        assert len(result.days) == 1
        # The surviving day must be the most recent one.
        assert result.days[0].day == DAY + _dt.timedelta(days=1)
        assert summarise_day(result.days[0]).minutes_of(Activity.DRIVING) == 60

    def test_overflow_keeps_the_newest_days(self):
        builder = CardDownloadBuilder(activity_buffer_len=60)
        for index in range(6):
            builder.add_simple_day(
                DAY + _dt.timedelta(days=index),
                [(0, Activity.WORK), (60, Activity.DRIVING), (120, Activity.BREAK_REST)],
            )
        result = parse_gen1(builder.build())
        assert 1 <= len(result.days) < 6
        # Newest day retained, oldest dropped.
        assert result.days[-1].day == DAY + _dt.timedelta(days=5)

    def test_cycle_is_broken_rather_than_looping_forever(self):
        """Corrupt pointers must terminate the walk, not hang the worker."""
        from tacho.parsers.gen1 import decode_driver_activity

        # A buffer of claim-two-bytes-pointing-at-itself.
        buffer = bytearray(40)
        buffer[0:2] = (0).to_bytes(2, "big")   # oldest
        buffer[2:4] = (0).to_bytes(2, "big")   # newest
        buffer[4:6] = (0).to_bytes(2, "big")   # prevLen
        buffer[6:8] = (2).to_bytes(2, "big")   # recLen = 2 -> invalid, must stop
        days, warnings = decode_driver_activity(bytes(buffer))
        assert days == []
        assert warnings


# ---------------------------------------------------------------------------
# Vehicle unit downloads: detected, then refused on purpose
# ---------------------------------------------------------------------------


class TestVehicleUnit:
    def test_vu_download_is_detected(self):
        result = parse_gen1(make_vu_download([1, 2, 3]))
        assert result.source_kind == VEHICLE_UNIT
        assert result.raw_evidence["treps"] == [1, 2, 3]
        assert "overview" in result.raw_evidence["trep_names"]
        assert "activities_for_date" in result.raw_evidence["trep_names"]

    def test_vu_bodies_are_refused_with_an_actionable_warning(self):
        result = parse_gen1(make_vu_download())
        assert result.days == []
        assert any("vehicle_unit_download_detected" in w for w in result.warnings)
        assert any("TACHO-SERVICE" in w for w in result.warnings)

    def test_trep_six_card_blob_is_excavated(self):
        """TREP 06 embeds a card-format download, which we *can* read."""
        card = make_sample_card_download(number_of_days=2)
        data = b"\x76\x06" + card
        result = parse_gen1(data)
        assert result.source_kind == VEHICLE_UNIT
        assert len(result.days) == 2
        assert any("TREP 06" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_default_registry_parses_a_card_download(self):
        registry = default_registry()
        assert len(registry.parsers) == 1  # no external parser configured
        result = registry.parse(make_sample_card_download(number_of_days=2))
        assert len(result.days) == 2

    def test_registry_failure_names_every_adapter(self):
        with pytest.raises(UnsupportedFileError) as excinfo:
            default_registry().parse(make_garbage())
        assert "clean-room-gen1" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Warnings must survive as warnings
# ---------------------------------------------------------------------------


def test_writer_rejects_an_empty_day():
    with pytest.raises(ValueError):
        CardDownloadBuilder().add_day(DAY, [])


def test_writer_rejects_a_download_with_no_days():
    with pytest.raises(ValueError):
        CardDownloadBuilder().build()


def test_card_not_inserted_minutes_are_reported_as_unknown():
    """A gap must surface as unknown, never be counted as rest."""
    builder = CardDownloadBuilder()
    builder.add_day(
        DAY,
        [
            ActivityChange(day=DAY, minute_of_day=0, activity=Activity.WORK),
            ActivityChange(
                day=DAY,
                minute_of_day=60,
                activity=Activity.BREAK_REST,
                card_not_inserted=True,
            ),
            ActivityChange(day=DAY, minute_of_day=180, activity=Activity.DRIVING),
        ],
    )
    result = parse_gen1(builder.build())
    totals = summarise_day(result.days[0])

    assert totals.minutes_of(Activity.WORK) == 60
    assert totals.minutes_of(Activity.DRIVING) == 24 * 60 - 180
    # 60..180 has no card: two hours of unknown, not two hours of rest.
    assert totals.uncovered_minutes == 120
    assert any("card_not_inserted_minutes=120" in w for w in totals.warnings)


def test_structural_location_does_not_depend_on_the_tag():
    """The EF identifier table is unverified, so detection must be structural.

    Rewrite the activity object with a deliberately wrong FID. The parser must
    still find it and say so.
    """
    from tacho.parsers.gen1 import FID_ICC, _u16

    original = make_sample_card_download(number_of_days=2)
    objects = iter_tlv(original)
    rebuilt = []
    renamed = False
    for obj in objects:
        if obj.fid == FID_DRIVER_ACTIVITY_DAILY_RECORDS_HINT and obj.is_data:
            rebuilt.append(
                FID_ICC.to_bytes(2, "big")
                + bytes([obj.suffix])
                + len(obj.value).to_bytes(2, "big")
                + obj.value
            )
            renamed = True
        else:
            rebuilt.append(
                obj.fid.to_bytes(2, "big")
                + bytes([obj.suffix])
                + len(obj.value).to_bytes(2, "big")
                + obj.value
            )
    assert renamed

    result = parse_gen1(b"".join(rebuilt))
    assert len(result.days) == 2
    assert any("located_structurally" in w for w in result.warnings)
    assert _u16(b"\x00\x02", 0) == FID_ICC
