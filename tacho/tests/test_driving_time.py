"""Driving-time engine tests.

Every expected number here is worked out by hand from the regulation text, not
copied from the engine's output. That is the whole point: a test that asserts
whatever the code already does proves nothing.

These tests establish that the engine is *internally correct and honest*. They do
**not** establish that it agrees with a trusted tachograph analysis report, which
is the validation the regulation-following spec asks for and which has not been
possible. See docs/DRIVING-TIME.md.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from tacho.domain.activities import (
    Activity,
    ActivityChange,
    ActivityDay,
    build_spans,
    summarise_day,
)
from tacho.rules.driving_time import (
    DAILY_DRIVING_EXTENDED_LIMIT,
    DAILY_DRIVING_LIMIT,
    ENGINE_VERSION,
    FORTNIGHTLY_DRIVING_LIMIT,
    REGULAR_DAILY_REST,
    REGULAR_WEEKLY_REST,
    RULES_VERSION,
    STATUS_INSUFFICIENT,
    STATUS_OK,
    STATUS_STALE,
    WEEKLY_DRIVING_LIMIT,
    CalculationResult,
    DayInput,
    assess_breaks,
    calculate,
    week_start,
)

# 2026-09-14 is a Monday, so week boundaries in these tests are easy to reason
# about: WEEK_DAY + n is the n-th day of that Monday-Sunday week.
WEEK_DAY = _dt.date(2026, 9, 14)


def make_day(
    day: _dt.date,
    pattern,
    *,
    import_id: int = 1,
    slot: int = 0,
) -> DayInput:
    """Build a ``DayInput`` from ``(minute, activity)`` pairs."""
    changes = [
        ActivityChange(day=day, minute_of_day=minute, activity=activity, slot=slot)
        for minute, activity in pattern
    ]
    activity_day = ActivityDay(
        day=day, presence_counter=1, distance_km=100, changes=tuple(changes)
    )
    totals = summarise_day(activity_day)
    return DayInput(
        day=day,
        spans=tuple(build_spans(activity_day)),
        uncovered_minutes=totals.uncovered_minutes,
        open_ended=totals.open_ended,
        import_id=import_id,
    )


def driving_day(day: _dt.date, hours: float, start_minute: int = 0) -> DayInput:
    """One continuous driving period of ``hours``, then rest until midnight.

    This is deliberately *non-compliant* with Article 7 for anything over 4.5
    hours; use it when the break rule is what is under test.
    """
    minutes = int(round(hours * 60))
    return make_day(
        day,
        [
            (start_minute, Activity.DRIVING),
            (start_minute + minutes, Activity.BREAK_REST),
        ],
    )


def legal_day(day: _dt.date, minutes: int, start_minute: int = 0) -> DayInput:
    """A day with ``minutes`` of driving, split by 45-minute breaks.

    Each driving period is kept at or below 4.5 hours, so Article 7 is satisfied
    and a test of an Article 6 limit measures that limit and nothing else. Without
    this, an "over 10 hours is a breach" test is contaminated by an Article 7
    breach that fires first and proves the wrong thing.
    """
    pattern = []
    cursor = start_minute
    remaining = minutes
    while remaining > 0:
        chunk = min(270, remaining)
        pattern.append((cursor, Activity.DRIVING))
        cursor += chunk
        remaining -= chunk
        if remaining > 0:
            pattern.append((cursor, Activity.BREAK_REST))
            cursor += 45
    pattern.append((cursor, Activity.BREAK_REST))
    return make_day(day, pattern)


def codes(result: CalculationResult):
    return [f.code for f in result.findings]


def breaches(result: CalculationResult):
    return [f for f in result.findings if f.is_breach]


def by_code(result: CalculationResult, code: str):
    return [f for f in result.findings if f.code == code]


# ---------------------------------------------------------------------------
# Versioning and honesty
# ---------------------------------------------------------------------------


class TestHonesty:
    def test_rules_and_engine_are_versioned(self):
        assert RULES_VERSION and ENGINE_VERSION
        assert "/" in RULES_VERSION  # regulation/version
        assert RULES_VERSION.startswith("eu-561-2006")

    def test_result_is_never_marked_validated(self):
        """No code path may set this True. It is the spec's core safety rail."""
        result = calculate("driver-1", [driving_day(WEEK_DAY, 8)])
        assert result.validated_against_reference is False
        assert "must not be presented as a legal finding" in result.validation_note
        assert result.as_dict()["validated_against_reference"] is False

    def test_assumptions_are_recorded(self):
        result = calculate("driver-1", [driving_day(WEEK_DAY, 8)])
        joined = " ".join(result.assumptions)
        assert "local wall clock" in joined
        assert "never as rest" in joined
        assert "Monday 00:00 to Sunday 24:00" in joined
        # Working time is explicitly out of scope.
        assert "2002/15/EC" in joined


# ---------------------------------------------------------------------------
# Article 6 — driving limits
# ---------------------------------------------------------------------------


class TestDailyDriving:
    def test_nine_hours_is_within_the_limit(self):
        result = calculate("d", [legal_day(WEEK_DAY, 540)])
        assert result.daily_driving[WEEK_DAY] == 540
        assert result.daily_driving[WEEK_DAY] == DAILY_DRIVING_LIMIT
        assert breaches(result) == []

    def test_one_minute_over_nine_hours_is_an_extension_not_a_breach(self):
        result = calculate("d", [legal_day(WEEK_DAY, 541)])
        assert result.daily_driving[WEEK_DAY] == 541
        # A single extension in the week is permitted, so no breach yet.
        assert breaches(result) == []

    def test_over_ten_hours_is_a_breach(self):
        result = calculate("d", [legal_day(WEEK_DAY, 601)])
        assert result.daily_driving[WEEK_DAY] == 601
        assert "daily_driving_exceeded_absolute" in codes(result)
        finding = by_code(result, "daily_driving_exceeded_absolute")[0]
        assert finding.limit_minutes == DAILY_DRIVING_EXTENDED_LIMIT
        assert finding.actual_minutes == 601

    def test_three_extensions_in_one_week_is_a_breach(self):
        """Art 6(1) allows the 10-hour extension at most twice per week."""
        days = [legal_day(WEEK_DAY + _dt.timedelta(days=offset), 570) for offset in range(3)]
        result = calculate("d", days)
        assert "daily_driving_extension_too_often" in codes(result)
        finding = by_code(result, "daily_driving_extension_too_often")[0]
        assert finding.evidence["extension_days"] == 3
        assert finding.day == WEEK_DAY

    def test_two_extensions_in_one_week_is_allowed(self):
        days = [legal_day(WEEK_DAY + _dt.timedelta(days=offset), 570) for offset in range(2)]
        result = calculate("d", days)
        assert "daily_driving_extension_too_often" not in codes(result)

    def test_extensions_are_counted_per_calendar_week_not_per_fortnight(self):
        """Two extensions on Sunday and two on the following Monday is legal."""
        sunday = WEEK_DAY + _dt.timedelta(days=6)
        monday = WEEK_DAY + _dt.timedelta(days=7)
        days = [
            legal_day(sunday, 570),
            legal_day(monday, 570),
            legal_day(monday + _dt.timedelta(days=1), 570),
        ]
        result = calculate("d", days)
        assert "daily_driving_extension_too_often" not in codes(result)
        assert week_start(sunday) != week_start(monday)


class TestWeeklyDriving:
    def test_six_ten_hour_days_breach_the_weekly_limit(self):
        """60 hours in a week exceeds Art 6(2)'s 56 hours.

        Note what else must be true: five 10-hour days already use the 10-hour
        extension five times, and Art 6(1) allows it twice. So a weekly breach is
        never the *only* breach — see the companion test below.
        """
        days = [
            legal_day(WEEK_DAY + _dt.timedelta(days=offset), 600)
            for offset in range(6)
        ]
        result = calculate("d", days)
        assert result.weekly_driving[WEEK_DAY] == 3600
        assert result.weekly_driving[WEEK_DAY] > WEEKLY_DRIVING_LIMIT
        assert "weekly_driving_exceeded" in codes(result)
        # Each day is within the 10-hour daily maximum, so no absolute daily
        # breach — but the extension was used six times, which is its own breach.
        assert "daily_driving_exceeded_absolute" not in codes(result)
        assert "daily_driving_extension_too_often" in codes(result)

    def test_the_weekly_limit_cannot_be_exceeded_within_the_other_limits(self):
        """The maximum week achievable without another breach is exactly 56 hours.

        Four 9-hour days plus two 10-hour days (using the only two permitted
        extensions) is 36 + 20 = 56 hours. That equals the Art 6(2) limit but does
        not exceed it. This is a useful invariant: it means any weekly breach comes
        with a companion breach, so a report showing only a weekly breach has a bug.
        """
        days = [
            legal_day(WEEK_DAY + _dt.timedelta(days=offset), 540) for offset in range(4)
        ] + [
            legal_day(WEEK_DAY + _dt.timedelta(days=offset), 600) for offset in range(4, 6)
        ]
        result = calculate("d", days)
        assert result.weekly_driving[WEEK_DAY] == 4 * 540 + 2 * 600 == 3360
        assert result.weekly_driving[WEEK_DAY] == WEEKLY_DRIVING_LIMIT
        assert "weekly_driving_exceeded" not in codes(result)
        assert "daily_driving_extension_too_often" not in codes(result)
        assert breaches(result) == []

    def test_five_ten_hour_days_are_within_the_weekly_limit(self):
        days = [
            legal_day(WEEK_DAY + _dt.timedelta(days=offset), 600)
            for offset in range(5)
        ]
        result = calculate("d", days)
        assert result.weekly_driving[WEEK_DAY] == 3000
        assert "weekly_driving_exceeded" not in codes(result)

    def test_weeks_are_split_on_monday(self):
        sunday = WEEK_DAY + _dt.timedelta(days=6)
        monday = WEEK_DAY + _dt.timedelta(days=7)
        result = calculate(
            "d", [legal_day(sunday, 480), legal_day(monday, 480)]
        )
        assert result.weekly_driving[week_start(sunday)] == 480
        assert result.weekly_driving[week_start(monday)] == 480


class TestFortnightlyDriving:
    def test_over_ninety_hours_in_two_weeks_is_a_breach(self):
        """48h + 48h = 96h across two consecutive weeks exceeds Art 6(3)."""
        days = []
        for offset in range(6):
            days.append(legal_day(WEEK_DAY + _dt.timedelta(days=offset), 480))
        for offset in range(6):
            days.append(
                legal_day(WEEK_DAY + _dt.timedelta(days=7 + offset), 480)
            )
        result = calculate("d", days)
        assert result.weekly_driving[WEEK_DAY] == 2880
        assert result.weekly_driving[WEEK_DAY + _dt.timedelta(days=7)] == 2880
        assert result.fortnightly_driving[WEEK_DAY] == 5760
        assert result.fortnightly_driving[WEEK_DAY] > FORTNIGHTLY_DRIVING_LIMIT
        assert "fortnightly_driving_exceeded" in codes(result)
        # 48h and 96h are both within the weekly and daily limits, so the two-week
        # rule is the only one breached.
        assert "weekly_driving_exceeded" not in codes(result)
        assert "fortnightly_driving_exceeded" in codes(result)

    def test_two_weeks_of_84_hours_is_within_the_limit(self):
        days = []
        for week in range(2):
            for offset in range(6):
                days.append(
                    legal_day(
                        WEEK_DAY + _dt.timedelta(days=week * 7 + offset), 420
                    )
                )
        result = calculate("d", days)
        assert sum(result.weekly_driving.values()) == 2 * 42 * 60
        assert result.fortnightly_driving[WEEK_DAY] == 2 * 42 * 60
        assert "fortnightly_driving_exceeded" not in codes(result)

    def test_a_fortnight_with_a_blank_week_is_reported_unknown(self):
        """A gap must not be summed as if it were zero hours."""
        days = [
            legal_day(WEEK_DAY, 480),
            legal_day(WEEK_DAY + _dt.timedelta(days=7), 480),
        ]
        result = calculate("d", days)
        assert "fortnightly_driving_unassessable" in codes(result)
        finding = by_code(result, "fortnightly_driving_unassessable")[0]
        assert finding.is_unknown
        assert finding.actual_minutes is None


# ---------------------------------------------------------------------------
# Article 7 — the 4.5-hour driving period and its break
# ---------------------------------------------------------------------------


class TestBreakRule:
    def test_exactly_four_and_a_half_hours_needs_no_break_yet(self):
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.DRIVING),          # 0 - 270, 4h30
                        (270, Activity.BREAK_REST),
                    ],
                )
            ],
        )
        assert "driving_period_without_qualifying_break" not in codes(result)

    def test_five_hours_straight_through_is_a_breach(self):
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.DRIVING),          # 0 - 300, 5h
                        (300, Activity.BREAK_REST),
                    ],
                )
            ],
        )
        assert "driving_period_without_qualifying_break" in codes(result)
        finding = by_code(result, "driving_period_without_qualifying_break")[0]
        assert finding.actual_minutes == 300
        assert finding.limit_minutes == 270
        assert "Art 7" in finding.article

    def test_a_single_forty_five_minute_break_resets_the_period(self):
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.DRIVING),          # 0 - 270
                        (270, Activity.BREAK_REST),     # 270 - 315, 45 min
                        (315, Activity.DRIVING),        # 315 - 585, 4h30
                        (585, Activity.BREAK_REST),
                    ],
                )
            ],
        )
        assert "driving_period_without_qualifying_break" not in codes(result)

    def test_the_split_fifteen_then_thirty_resets_the_period(self):
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.DRIVING),          # 0 - 120, 2h
                        (120, Activity.BREAK_REST),     # 120 - 135, 15 min
                        (135, Activity.DRIVING),        # 135 - 255, 2h
                        (255, Activity.BREAK_REST),     # 255 - 285, 30 min
                        (285, Activity.DRIVING),        # 285 - 555, 4h30
                        (555, Activity.BREAK_REST),
                    ],
                )
            ],
        )
        assert "driving_period_without_qualifying_break" not in codes(result)

    def test_fifteen_alone_does_not_satisfy_the_break(self):
        """15 + 20 min totals 35, short of the 45 required."""
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.DRIVING),          # 0 - 120
                        (120, Activity.BREAK_REST),     # 120 - 135, 15
                        (135, Activity.DRIVING),        # 135 - 255
                        (255, Activity.BREAK_REST),     # 255 - 275, 20
                        (275, Activity.DRIVING),        # 275 - 560, 4h45
                        (560, Activity.BREAK_REST),
                    ],
                )
            ],
        )
        assert "driving_period_without_qualifying_break" in codes(result)

    def test_a_break_under_fifteen_minutes_does_not_count(self):
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.DRIVING),          # 0 - 120
                        (120, Activity.BREAK_REST),     # 10 min, below the minimum
                        (130, Activity.DRIVING),        # 130 - 400, 4h30
                        (400, Activity.BREAK_REST),
                    ],
                )
            ],
        )
        assert "driving_period_without_qualifying_break" in codes(result)
        assert any("below_the_15_minute_minimum" in w for w in result.warnings)

    def test_other_work_does_not_satisfy_the_break(self):
        """Art 4(d): a break is used exclusively for recuperation.

        Four hours of driving, an hour of other work, then two more hours of
        driving is a six-hour driving period and a breach.
        """
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.DRIVING),          # 0 - 240, 4h
                        (240, Activity.WORK),           # 240 - 300, 1h other work
                        (300, Activity.DRIVING),        # 300 - 420, 2h
                        (420, Activity.BREAK_REST),
                    ],
                )
            ],
        )
        assert "driving_period_without_qualifying_break" in codes(result)
        assert by_code(result, "driving_period_without_qualifying_break")[0].actual_minutes == 360

    def test_availability_does_not_satisfy_the_break_either(self):
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.DRIVING),
                        (240, Activity.AVAILABILITY),   # 240 - 300
                        (300, Activity.DRIVING),
                        (420, Activity.BREAK_REST),
                    ],
                )
            ],
        )
        assert "driving_period_without_qualifying_break" in codes(result)

    def test_the_driving_period_crosses_midnight(self):
        """4h before midnight plus 1h after is a 5-hour driving period.

        This is the violation a per-day implementation misses, so it is pinned
        down explicitly.
        """
        first = make_day(
            WEEK_DAY,
            [(20 * 60, Activity.DRIVING), (24 * 60, Activity.BREAK_REST)],
        )
        second = make_day(
            WEEK_DAY + _dt.timedelta(days=1),
            [
                (0, Activity.DRIVING),
                (60, Activity.BREAK_REST),
            ],
        )
        result = calculate("d", [first, second])
        assert "driving_period_without_qualifying_break" in codes(result)
        finding = by_code(result, "driving_period_without_qualifying_break")[0]
        assert finding.actual_minutes == 300

    def test_an_open_ended_record_makes_the_period_unknown(self):
        """The last span of a record has no closing change: do not guess."""
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.WORK),
                        (60, Activity.DRIVING),
                        (300, Activity.WORK),
                        (600, Activity.AVAILABILITY),
                    ],
                )
            ],
        )
        # 240 minutes of driving, then other work, then availability, then the
        # record stops. Availability is not a break, so the driving period is still
        # open when the data ends and nothing may be concluded about what followed.
        assert "break_rule_unassessable_open_record" in codes(result)
        finding = by_code(result, "break_rule_unassessable_open_record")[0]
        assert finding.is_unknown
        assert finding.actual_minutes is None
        assert finding.evidence["driving_since_last_qualifying_break"] == 240
        # Critically: not reported as a breach, because the data does not support
        # that claim either.
        assert "driving_period_without_qualifying_break" not in codes(result)


# ---------------------------------------------------------------------------
# Article 8 — rest
# ---------------------------------------------------------------------------


class TestDailyRest:
    def test_an_eleven_hour_rest_is_regular(self):
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.BREAK_REST),       # 0 - 660, 11h regular
                        (660, Activity.DRIVING),        # 660 - 1000
                        (1000, Activity.BREAK_REST),    # 1000 - midnight, open-ended
                    ],
                )
            ],
        )
        # The trailing block runs off the end of the data, so it must be reported
        # as unknown rather than as a rest that is too short.
        assert "rest_block_below_daily_rest_minimum" not in codes(result)
        assert "rest_block_open_at_end_of_data" in codes(result)
        assert result.daily_driving[WEEK_DAY] == 340

    def test_a_three_plus_nine_split_counts_as_a_daily_rest(self):
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.BREAK_REST),       # 3h
                        (180, Activity.WORK),           # 1h
                        (240, Activity.BREAK_REST),     # 9h
                        (780, Activity.DRIVING),
                        (900, Activity.BREAK_REST),
                    ],
                )
            ],
        )
        assert "rest_block_below_daily_rest_minimum" not in codes(result)

    def test_a_four_hour_rest_is_not_a_daily_rest(self):
        """Above the 3-hour floor of a split rest, below the 9-hour reduced minimum."""
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.BREAK_REST),       # 0 - 240, 4h only
                        (240, Activity.WORK),           # 240 - 1440, open-ended
                    ],
                )
            ],
        )
        assert "rest_block_below_daily_rest_minimum" in codes(result)
        finding = by_code(result, "rest_block_below_daily_rest_minimum")[0]
        assert finding.is_unknown
        assert finding.actual_minutes == 240

    def test_a_two_hour_rest_is_neither_counted_nor_condemned(self):
        """Below the 3-hour floor it is not a daily rest and produces no finding.

        It could legitimately be a break, so reporting it as a failed daily rest
        would be noise. What matters is that it is not *counted* as one.
        """
        result = calculate(
            "d",
            [
                make_day(
                    WEEK_DAY,
                    [
                        (0, Activity.BREAK_REST),       # 2h
                        (120, Activity.WORK),
                        (240, Activity.BREAK_REST),     # 18h, regular
                    ],
                )
            ],
        )
        assert "rest_block_below_daily_rest_minimum" not in codes(result)
        assert "reduced_daily_rest_count" not in codes(result)

    def _reduced_rest_days(self, count: int):
        """``count`` days, each with exactly one 9h30 rest that does not cross midnight.

        Ending each day with other work rather than rest is deliberate: an evening
        rest that runs into the next morning is a *single continuous* period, so a
        rest from 17:00 to 09:30 is one regular 16.5-hour daily rest and not two
        reduced ones. Constructing the fixture the naive way produces regular rests
        and tests nothing about Art 8(4).
        """
        return [
            make_day(
                WEEK_DAY + _dt.timedelta(days=offset),
                [
                    (0, Activity.BREAK_REST),       # 0 - 570 = 9h30 reduced
                    (570, Activity.DRIVING),        # exactly 4h30, no Art 7 breach
                    (840, Activity.WORK),           # runs to midnight
                ],
            )
            for offset in range(count)
        ]

    def test_four_reduced_daily_rests_are_flagged(self):
        result = calculate("d", self._reduced_rest_days(4))
        assert "reduced_daily_rest_count" in codes(result)
        finding = by_code(result, "reduced_daily_rest_count")[0]
        assert finding.severity == "warning"
        assert "Art 8(4)" in finding.article
        assert finding.actual_minutes == 4

    def test_three_reduced_daily_rests_are_allowed(self):
        """The Art 8(4) boundary: three is permitted, the fourth is not."""
        result = calculate("d", self._reduced_rest_days(3))
        assert "reduced_daily_rest_count" not in codes(result)

    def test_rest_is_never_inferred_across_a_gap(self):
        """Two rest blocks either side of a missing day must not be merged.

        Bridging them is how an engine turns an unrecorded night into a compliant
        45-hour weekly rest. The precise assertion is on the block structure: two
        blocks, not one — so the gap is genuinely preserved.
        """
        from tacho.rules.driving_time import _rest_blocks

        first = make_day(
            WEEK_DAY,
            [(0, Activity.DRIVING), (120, Activity.BREAK_REST)],  # rest 02:00 -> midnight
        )
        third = make_day(
            WEEK_DAY + _dt.timedelta(days=2),
            [(0, Activity.BREAK_REST), (60, Activity.DRIVING), (200, Activity.BREAK_REST)],
        )
        result = calculate("d", [first, third])

        assert WEEK_DAY + _dt.timedelta(days=1) in result.missing_days
        assert result.status == STATUS_INSUFFICIENT

        blocks = _rest_blocks([first, third])
        # Day one's rest ends at the end of day one (minute 1440) and the next block
        # does not begin until the start of day three (minute 2880): a 1440-minute
        # hole that must not be filled in.
        assert blocks[0][1] == 24 * 60
        assert blocks[1][0] == 2 * 24 * 60
        assert blocks[1][0] - blocks[0][1] == 24 * 60
        # Neither block reaches the 24-hour reduced weekly rest minimum, so no
        # weekly rest may be credited from them.
        assert all((end - start) < 24 * 60 for start, end, _day, _open in blocks)
        assert "weekly_rest_reduced_compensation_required" not in codes(result)


class TestWeeklyRest:
    def test_a_forty_five_hour_rest_satisfies_the_week(self):
        days = []
        for offset in range(7):
            day = WEEK_DAY + _dt.timedelta(days=offset)
            if offset in (0, 1):
                # Saturday+Sunday style 45-hour rest at the start of the week.
                days.append(
                    make_day(
                        day,
                        [(0, Activity.BREAK_REST), (24 * 60, Activity.BREAK_REST)],
                    )
                )
            else:
                days.append(
                    make_day(
                        day,
                        [
                            (0, Activity.WORK),
                            (120, Activity.DRIVING),
                            (600, Activity.WORK),
                            (660, Activity.BREAK_REST),
                        ],
                    )
                )
        result = calculate("d", days)
        assert "weekly_rest_not_found" not in codes(result)

    def test_a_full_week_with_no_long_rest_is_a_breach(self):
        days = [
            make_day(
                WEEK_DAY + _dt.timedelta(days=offset),
                [
                    (0, Activity.WORK),
                    (120, Activity.DRIVING),
                    (600, Activity.WORK),
                    (600 + 60, Activity.BREAK_REST),  # only 1h at the end of each day
                ],
            )
            for offset in range(7)
        ]
        result = calculate("d", days)
        assert "weekly_rest_not_found" in codes(result)
        assert by_code(result, "weekly_rest_not_found")[0].day == WEEK_DAY

    def test_a_partly_covered_week_is_unknown_not_a_breach(self):
        days = [driving_day(WEEK_DAY, 8), driving_day(WEEK_DAY + _dt.timedelta(days=1), 8)]
        result = calculate("d", days)
        assert "weekly_rest_unassessable_partial_week" in codes(result)
        assert "weekly_rest_not_found" not in codes(result)

    def test_a_reduced_weekly_rest_demands_compensation(self):
        days = []
        for offset in range(7):
            day = WEEK_DAY + _dt.timedelta(days=offset)
            if offset == 0:
                # 30 hours of rest: reduced, needs compensation.
                days.append(make_day(day, [(0, Activity.BREAK_REST), (1800, Activity.WORK)]))
            elif offset == 1:
                days.append(make_day(day, [(0, Activity.WORK), (1440, Activity.BREAK_REST)]))
            else:
                days.append(
                    make_day(
                        day,
                        [
                            (0, Activity.WORK),
                            (120, Activity.DRIVING),
                            (660, Activity.BREAK_REST),
                        ],
                    )
                )
        result = calculate("d", days)
        assert "weekly_rest_reduced_compensation_required" in codes(result)
        finding = by_code(result, "weekly_rest_reduced_compensation_required")[0]
        assert "Art 8(6b)" in finding.article
        assert finding.evidence["compensation_verified"] is False


# ---------------------------------------------------------------------------
# Coverage, staleness and the status field
# ---------------------------------------------------------------------------


class TestCoverageAndStatus:
    def test_full_clean_coverage_is_ok(self):
        result = calculate("d", [driving_day(WEEK_DAY, 8)])
        assert result.missing_days == []
        assert result.status == STATUS_INSUFFICIENT or result.status == STATUS_OK
        # A single open-ended day cannot be called fully assessed, so the only
        # acceptable values here are insufficient or ok — never 'stale'.
        assert result.status in (STATUS_OK, STATUS_INSUFFICIENT)

    def test_a_missing_day_is_recorded_and_lowers_the_status(self):
        days = [
            driving_day(WEEK_DAY, 8),
            driving_day(WEEK_DAY + _dt.timedelta(days=2), 8),
        ]
        result = calculate("d", days)
        assert WEEK_DAY + _dt.timedelta(days=1) in result.missing_days
        assert result.status == STATUS_INSUFFICIENT
        assert any("missing_activity_days=1" in w for w in result.warnings)

    def test_stale_data_is_reported_as_stale_and_not_calculated_as_current(self):
        result = calculate(
            "d", [driving_day(WEEK_DAY, 8)], data_age_days=40
        )
        assert result.status == STATUS_STALE
        assert any("stale" in w for w in result.warnings)

    def test_recent_data_is_not_stale(self):
        result = calculate("d", [driving_day(WEEK_DAY, 8)], data_age_days=3)
        assert result.status != STATUS_STALE

    def test_no_data_at_all(self):
        result = calculate("d", [])
        assert result.status == STATUS_INSUFFICIENT
        assert "no_data" in codes(result)
        assert result.daily_driving == {}

    def test_period_boundaries_are_respected(self):
        days = [
            driving_day(WEEK_DAY, 8),
            driving_day(WEEK_DAY + _dt.timedelta(days=1), 8),
        ]
        result = calculate(
            "d", days, period_start=WEEK_DAY, period_end=WEEK_DAY + _dt.timedelta(days=3)
        )
        assert result.period_start == WEEK_DAY
        assert result.period_end == WEEK_DAY + _dt.timedelta(days=3)
        # Days two and three of the requested span have no record.
        assert len(result.missing_days) == 2

    def test_source_imports_are_recorded_for_traceability(self):
        days = [
            driving_day(WEEK_DAY, 8),
            driving_day(WEEK_DAY + _dt.timedelta(days=1), 8),
        ]
        days[0] = DayInput(
            day=days[0].day,
            spans=days[0].spans,
            uncovered_minutes=days[0].uncovered_minutes,
            open_ended=days[0].open_ended,
            import_id=7,
        )
        days[1] = DayInput(
            day=days[1].day,
            spans=days[1].spans,
            uncovered_minutes=days[1].uncovered_minutes,
            open_ended=days[1].open_ended,
            import_id=9,
        )
        result = calculate("d", days)
        assert result.source_import_ids == [7, 9]
        assert result.as_dict()["source_import_ids"] == [7, 9]

    def test_result_serialises_to_json_safe_types(self):
        import json

        result = calculate("driver-key", [driving_day(WEEK_DAY, 8)])
        payload = json.loads(json.dumps(result.as_dict()))
        assert payload["rules_version"] == RULES_VERSION
        assert payload["period_start"] == WEEK_DAY.isoformat()
        assert isinstance(payload["findings"], list)


# ---------------------------------------------------------------------------
# A whole week, checked by hand
# ---------------------------------------------------------------------------


def test_a_realistic_week_and_its_expected_numbers():
    """Mon-Sat at 8h driving, Sunday off with a 45-hour rest.

    Hand-computed: 6 x 8h = 48h weekly, under the 56h limit; each day is under
    9h so no extension; total 2880 minutes.
    """
    days = []
    for offset in range(6):
        days.append(driving_day(WEEK_DAY + _dt.timedelta(days=offset), 8))
    days.append(
        make_day(
            WEEK_DAY + _dt.timedelta(days=6),
            [
                (0, Activity.BREAK_REST),      # full day off
                (24 * 60, Activity.BREAK_REST),
            ],
        )
    )
    result = calculate("d", days)

    assert sum(result.daily_driving.values()) == 6 * 8 * 60 == 2880
    assert result.weekly_driving[WEEK_DAY] == 2880
    assert result.weekly_driving[WEEK_DAY] < WEEKLY_DRIVING_LIMIT
    assert "weekly_driving_exceeded" not in codes(result)
    assert "daily_driving_extension_too_often" not in codes(result)
    # Each day is 8 hours of *continuous* driving, which is one driving period of
    # four and a half hours plus more, so Article 7 is breached on every one of the
    # six days. This is the case a per-day implementation gets right by accident
    # and a naive one misses.
    assert len(by_code(result, "driving_period_without_qualifying_break")) == 6
    assert "weekly_driving_exceeded" not in codes(result)
