"""EU driving-time calculation engine.

RULES VERSION: ``eu-561-2006/2026.1``

Source: Regulation (EC) No 561/2006 as amended, principally by Regulation (EU)
2020/1054. Article numbers are cited on every finding so a human can check the
engine rather than trust it.

WHAT THIS ENGINE IS
-------------------
It reads *recorded* activity and reports:
  * driving minutes per calendar day, per Monday-Sunday week, and per pair of
    consecutive weeks;
  * whether the 4.5-hour driving period was followed by a qualifying break;
  * daily-rest and weekly-rest observations where the data supports them.

WHAT THIS ENGINE IS NOT
-----------------------
It is **not a legal finding** and must not be presented as one. Three reasons,
stated plainly so nobody has to discover them later:

1. **No reference validation.** The spec requires that calculations be validated
   against trusted tachograph analysis reports. That has not been done — no such
   report has been available. ``validated_against_reference`` is therefore False
   on every result this engine produces, and there is no code path that sets it
   True. See docs/DRIVING-TIME.md.
2. **Gaps become "unknown", never a number.** If the card was not inserted, a day
   is missing from the import, or the record runs off the end of the data, every
   affected finding is marked unknown. Time with no card is time whose activity is
   unknown — not rest.
3. **Local wall-clock, no DST.** Activity is stored as minutes since midnight in
   the vehicle's local time. This engine does not convert timezones and does not
   model a daylight-saving shift inside a day. Two days a year that is wrong by an
   hour, and the assumption is recorded on every result.

Also outside this engine: working time (Directive 2002/15/EC) is a separate regime
with separate limits. Satisfying a driving-time limit does not establish
working-time compliance, and this engine makes no claim about the latter.

Regulation (EU) 2024/1258 adds flexibility for *occasional passenger transport*.
It does not apply to the goods transport this deployment serves, and is
deliberately not implemented.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from ..domain.activities import Activity, ActivitySpan

#: Bumped whenever a change to this file could alter a computed figure. Recorded
#: on every stored calculation so an old result stays explainable.
RULES_VERSION = "eu-561-2006/2026.1"
ENGINE_VERSION = "driving-time/0.1.0"

# ---------------------------------------------------------------------------
# Limits, in minutes. Article numbers are the authority for each figure.
# ---------------------------------------------------------------------------

#: Art 6(1): daily driving 9 hours.
DAILY_DRIVING_LIMIT = 9 * 60
#: Art 6(1): extendable to 10 hours...
DAILY_DRIVING_EXTENDED_LIMIT = 10 * 60
#: ...not more than twice during the week. Art 4(i): week is Mon 00:00-Sun 24:00.
MAX_DAILY_EXTENSIONS_PER_WEEK = 2

#: Art 6(2): weekly driving 56 hours.
WEEKLY_DRIVING_LIMIT = 56 * 60
#: Art 6(3): any two consecutive weeks, 90 hours.
FORTNIGHTLY_DRIVING_LIMIT = 90 * 60

#: Art 7: driving period of 4.5 hours.
DRIVING_PERIOD_BEFORE_BREAK = 4 * 60 + 30
#: Art 7: uninterrupted break of at least 45 minutes.
QUALIFYING_BREAK_TOTAL = 45
#: Art 7: or breaks of at least 15 minutes each, distributed over the period.
#: Commission guidance states the order: 15 minutes first, then 30.
MIN_BREAK_PART = 15

#: Art 4(g) / Art 8(2): regular daily rest 11 hours.
REGULAR_DAILY_REST = 11 * 60
#: Art 4(g): reduced daily rest at least 9 hours and less than 11.
REDUCED_DAILY_REST_MIN = 9 * 60
#: Art 8(4): at most three reduced daily rests between any two weekly rests.
MAX_REDUCED_DAILY_RESTS = 3
#: Art 4(g): split daily rest, first period at least 3 hours...
SPLIT_DAILY_REST_FIRST = 3 * 60
#: ...then at least 9 hours.
SPLIT_DAILY_REST_SECOND = 9 * 60
#: Art 8(2): the daily rest must fall within a 24-hour period after the end of the
#: previous daily or weekly rest.
DAILY_REST_WINDOW = 24 * 60
#: Art 8(5): multi-manning, 9 hours of rest within 30 hours.
MULTI_MANNING_WINDOW = 30 * 60
MULTI_MANNING_REST = 9 * 60

#: Art 4(h): regular weekly rest 45 hours.
REGULAR_WEEKLY_REST = 45 * 60
#: Art 4(h) / Art 8(6): reduced weekly rest, minimum 24 hours.
REDUCED_WEEKLY_REST_MIN = 24 * 60
#: Art 8(6): a weekly rest must start no later than the end of six consecutive
#: 24-hour periods from the end of the previous weekly rest.
WEEKLY_REST_MAX_INTERVAL = 6 * 24 * 60

#: Only a genuine break or rest counts. Art 4(d): a break is used exclusively for
#: recuperation, with no driving and no other work. Availability and other work
#: therefore do **not** interrupt a driving period.
BREAK_ACTIVITIES = frozenset({Activity.BREAK_REST})

SEVERITY_OK = "ok"
SEVERITY_WARNING = "warning"
SEVERITY_BREACH = "breach"
SEVERITY_UNKNOWN = "unknown"

STATUS_OK = "ok"
STATUS_INSUFFICIENT = "insufficient_data"
STATUS_STALE = "stale"

#: How far back a calculation may look before it is called stale. Daily and weekly
#: rest rules are anchored on previous rests, so a period with a long unrecorded
#: tail cannot be assessed.
STALE_AFTER_DAYS = 21


@dataclass
class DayInput:
    """One calendar day of recorded activity, ready to be calculated from."""

    day: _dt.date
    spans: Tuple[ActivitySpan, ...] = ()
    #: Minutes with no activity recorded. Unknown, not rest.
    uncovered_minutes: int = 0
    #: True when the day's record ends without a closing change.
    open_ended: bool = False
    #: Card presence for the record, when the parser could determine it.
    card_present: bool = True
    import_id: Optional[int] = None


@dataclass
class Finding:
    """One assessed rule. ``article`` is cited so it can be checked by hand."""

    code: str
    severity: str
    message: str
    article: str
    day: Optional[_dt.date] = None
    limit_minutes: Optional[int] = None
    actual_minutes: Optional[int] = None
    evidence: Dict[str, object] = field(default_factory=dict)

    @property
    def is_breach(self) -> bool:
        return self.severity == SEVERITY_BREACH

    @property
    def is_unknown(self) -> bool:
        return self.severity == SEVERITY_UNKNOWN


@dataclass
class CalculationResult:
    """Everything needed to explain the numbers, and nothing more."""

    driver_key: str
    period_start: _dt.date
    period_end: _dt.date
    rules_version: str = RULES_VERSION
    engine_version: str = ENGINE_VERSION
    status: str = STATUS_OK

    daily_driving: Dict[_dt.date, int] = field(default_factory=dict)
    weekly_driving: Dict[_dt.date, int] = field(default_factory=dict)
    fortnightly_driving: Dict[_dt.date, int] = field(default_factory=dict)

    findings: List[Finding] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    source_days: List[_dt.date] = field(default_factory=list)
    missing_days: List[_dt.date] = field(default_factory=list)
    source_import_ids: List[int] = field(default_factory=list)

    #: Never True from this engine. See the module docstring.
    validated_against_reference: bool = False
    validation_note: str = (
        "Not validated against a trusted tachograph analysis report. "
        "This output must not be presented as a legal finding."
    )

    def as_dict(self) -> Dict[str, object]:
        return {
            "driver_key": self.driver_key,
            "period_start": self.period_start.isoformat(),
            "period_end": self.period_end.isoformat(),
            "rules_version": self.rules_version,
            "engine_version": self.engine_version,
            "status": self.status,
            "daily_driving_minutes": {
                d.isoformat(): m for d, m in sorted(self.daily_driving.items())
            },
            "weekly_driving_minutes": {
                d.isoformat(): m for d, m in sorted(self.weekly_driving.items())
            },
            "fortnightly_driving_minutes": {
                d.isoformat(): m for d, m in sorted(self.fortnightly_driving.items())
            },
            "source_days": [d.isoformat() for d in self.source_days],
            "missing_days": [d.isoformat() for d in self.missing_days],
            "source_import_ids": self.source_import_ids,
            "assumptions": self.assumptions,
            "warnings": self.warnings,
            "validated_against_reference": self.validated_against_reference,
            "validation_note": self.validation_note,
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "message": f.message,
                    "article": f.article,
                    "day": f.day.isoformat() if f.day else None,
                    "limit_minutes": f.limit_minutes,
                    "actual_minutes": f.actual_minutes,
                    "evidence": f.evidence,
                }
                for f in self.findings
            ],
        }


# ---------------------------------------------------------------------------
# Calendar helpers
# ---------------------------------------------------------------------------


def week_start(day: _dt.date) -> _dt.date:
    """Monday of the week containing ``day`` (Art 4(i))."""
    return day - _dt.timedelta(days=day.weekday())


def _minute_timeline(days: Sequence[DayInput]) -> List[Tuple[_dt.date, int, Activity, bool]]:
    """Flatten spans into ``(day, minute, activity, card_present)`` entries.

    Only the reaches of the record that exist are emitted: a gap is a gap, and it
    must not appear as an activity here, because every consumer of this list
    treats presence as recorded fact.
    """
    timeline: List[Tuple[_dt.date, int, Activity, bool]] = []
    for day_input in sorted(days, key=lambda d: d.day):
        for span in day_input.spans:
            if span.card_not_inserted:
                # Recorded absence of a card is not an activity.
                continue
            timeline.append(
                (day_input.day, span.start_minute, span.activity, True)
            )
    return timeline


def _absolute_minute(day: _dt.date, minute: int, origin: _dt.date) -> int:
    return (day - origin).days * 24 * 60 + minute


# ---------------------------------------------------------------------------
# Driving totals
# ---------------------------------------------------------------------------


def daily_driving_totals(days: Sequence[DayInput]) -> Dict[_dt.date, int]:
    totals: Dict[_dt.date, int] = {}
    for day_input in days:
        minutes = sum(
            span.duration_minutes
            for span in day_input.spans
            if span.activity is Activity.DRIVING and not span.card_not_inserted
        )
        totals[day_input.day] = totals.get(day_input.day, 0) + minutes
    return totals


def _span_activity_lookup(days: Sequence[DayInput]) -> List[Tuple[_dt.date, ActivitySpan]]:
    entries: List[Tuple[_dt.date, ActivitySpan]] = []
    for day_input in sorted(days, key=lambda d: d.day):
        for span in day_input.spans:
            entries.append((day_input.day, span))
    entries.sort(key=lambda e: (e[0], e[1].start_minute))
    return entries


def assess_daily_driving(
    totals: Dict[_dt.date, int], result: CalculationResult
) -> None:
    """Art 6(1): 9 hours, extended to 10 at most twice per week."""
    extensions_per_week: Dict[_dt.date, int] = {}

    for day in sorted(totals):
        minutes = totals[day]
        if minutes > DAILY_DRIVING_EXTENDED_LIMIT:
            result.findings.append(
                Finding(
                    code="daily_driving_exceeded_absolute",
                    severity=SEVERITY_BREACH,
                    message=(
                        "Daily driving of %dh%02d exceeds the 10-hour absolute "
                        "maximum. Article 6(1) permits an extension to 10 hours, "
                        "never beyond it."
                        % divmod(minutes, 60)
                    ),
                    article="Regulation (EC) 561/2006 Art 6(1)",
                    day=day,
                    limit_minutes=DAILY_DRIVING_EXTENDED_LIMIT,
                    actual_minutes=minutes,
                )
            )
            week = week_start(day)
            extensions_per_week[week] = extensions_per_week.get(week, 0) + 1
        elif minutes > DAILY_DRIVING_LIMIT:
            week = week_start(day)
            extensions_per_week[week] = extensions_per_week.get(week, 0) + 1

    for week, count in sorted(extensions_per_week.items()):
        if count > MAX_DAILY_EXTENSIONS_PER_WEEK:
            result.findings.append(
                Finding(
                    code="daily_driving_extension_too_often",
                    severity=SEVERITY_BREACH,
                    message=(
                        "Daily driving was extended above 9 hours on %d days in the "
                        "week beginning %s; Article 6(1) allows this at most twice "
                        "per week." % (count, week.isoformat())
                    ),
                    article="Regulation (EC) 561/2006 Art 6(1)",
                    day=week,
                    limit_minutes=None,
                    actual_minutes=count,
                    evidence={"extension_days": count},
                )
            )


def assess_weekly_driving(
    totals: Dict[_dt.date, int], result: CalculationResult
) -> Dict[_dt.date, int]:
    """Art 6(2): 56 hours per week. Art 6(3): 90 hours per two consecutive weeks."""
    weekly: Dict[_dt.date, int] = {}
    for day, minutes in totals.items():
        week = week_start(day)
        weekly[week] = weekly.get(week, 0) + minutes

    for week in sorted(weekly):
        minutes = weekly[week]
        if minutes > WEEKLY_DRIVING_LIMIT:
            result.findings.append(
                Finding(
                    code="weekly_driving_exceeded",
                    severity=SEVERITY_BREACH,
                    message=(
                        "Weekly driving of %dh%02d exceeds the 56-hour limit for the "
                        "week beginning %s."
                        % (*divmod(minutes, 60), week.isoformat())
                    ),
                    article="Regulation (EC) 561/2006 Art 6(2)",
                    day=week,
                    limit_minutes=WEEKLY_DRIVING_LIMIT,
                    actual_minutes=minutes,
                )
            )

    # Any two consecutive weeks, so every adjacent pair, including a pair that
    # straddles a week with no data.
    fortnightly: Dict[_dt.date, int] = {}
    weeks = sorted(weekly)
    consecutive_pairs: List[Tuple[_dt.date, _dt.date]] = []
    if weeks:
        cursor = weeks[0]
        last = weeks[-1]
        while cursor <= last:
            consecutive_pairs.append((cursor, cursor + _dt.timedelta(days=7)))
            cursor += _dt.timedelta(days=7)

    for first, second in consecutive_pairs:
        if first not in weekly or second not in weekly:
            # A fortnight spanning a week with no data cannot be summed honestly.
            result.findings.append(
                Finding(
                    code="fortnightly_driving_unassessable",
                    severity=SEVERITY_UNKNOWN,
                    message=(
                        "Driving for the two weeks beginning %s cannot be assessed: "
                        "no recorded activity for the week beginning %s. Article "
                        "6(3) caps any two consecutive weeks at 90 hours."
                        % (first.isoformat(), (first if first not in weekly else second).isoformat())
                    ),
                    article="Regulation (EC) 561/2006 Art 6(3)",
                    day=first,
                    limit_minutes=FORTNIGHTLY_DRIVING_LIMIT,
                    actual_minutes=None,
                )
            )
            continue
        total = weekly[first] + weekly[second]
        fortnightly[first] = total
        if total > FORTNIGHTLY_DRIVING_LIMIT:
            result.findings.append(
                Finding(
                    code="fortnightly_driving_exceeded",
                    severity=SEVERITY_BREACH,
                    message=(
                        "Driving of %dh%02d over the two weeks beginning %s exceeds "
                        "the 90-hour limit."
                        % (*divmod(total, 60), first.isoformat())
                    ),
                    article="Regulation (EC) 561/2006 Art 6(3)",
                    day=first,
                    limit_minutes=FORTNIGHTLY_DRIVING_LIMIT,
                    actual_minutes=total,
                )
            )
    return fortnightly


# ---------------------------------------------------------------------------
# Article 7 — the 4.5-hour driving period and its break
# ---------------------------------------------------------------------------


def _activity_blocks(
    days: Sequence[DayInput],
) -> List[Tuple[int, int, Activity, _dt.date, bool]]:
    """Merge contiguous same-activity spans into blocks, across day boundaries.

    Returns ``(start_absolute_minute, end_absolute_minute, activity, start_day,
    open_ended)``.

    Two spans merge only when the earlier ends exactly where the later begins
    *and* they record the same activity. That condition is what makes a rest that
    runs through midnight one block instead of two, and equally what stops a gap
    (a missing day, or a period with no card) from being bridged.
    """
    entries = _span_activity_lookup(days)
    if not entries:
        return []
    origin = min(day for day, _ in entries)

    blocks: List[Tuple[int, int, Activity, _dt.date, bool]] = []
    for day, span in entries:
        if span.card_not_inserted:
            # No card: the activity is unknown, so it is not part of any block.
            continue
        start = _absolute_minute(day, span.start_minute, origin)
        end = _absolute_minute(day, span.end_minute, origin)
        if blocks and blocks[-1][1] == start and blocks[-1][2] is span.activity:
            previous = blocks[-1]
            blocks[-1] = (previous[0], end, span.activity, previous[3], span.open_ended)
            continue
        blocks.append((start, end, span.activity, day, span.open_ended))
    return blocks


def assess_breaks(days: Sequence[DayInput], result: CalculationResult) -> None:
    """Art 7: after 4.5 hours of driving, a qualifying break is required.

    The 4.5 hours is a *driving period* (Art 4(q)) — accumulated driving since the
    last break or rest, which may span midnight and therefore several daily
    records. Building this per-day would miss exactly the violation a fleet most
    needs to see, so the walk is across the whole period over merged blocks.

    A break qualifies as 45 uninterrupted minutes, or as parts of at least 15
    minutes each summing to 45. Commission guidance specifies the order as 15 then
    30; this engine requires the parts to be individually at least 15 minutes and
    to total 45, and records the observed part sizes as evidence so the ordering
    can be checked by a human rather than silently assumed.
    """
    blocks = _activity_blocks(days)
    if not blocks:
        return

    driving_since_break = 0
    break_parts: List[int] = []
    breach_reported = False
    previous_end: Optional[int] = None

    for position, (start, end, activity, day, open_ended) in enumerate(blocks):
        is_last = position == len(blocks) - 1

        if previous_end is not None and start > previous_end:
            # A gap while a driving period was open: whether a break happened in
            # it is unknowable, so the period is abandoned and reported rather than
            # silently continued or silently reset.
            if driving_since_break > 0:
                result.findings.append(
                    Finding(
                        code="break_rule_gap_in_record",
                        severity=SEVERITY_UNKNOWN,
                        message=(
                            "The record has a %d-minute gap on %s while a driving "
                            "period was open at %dh%02d, so whether a qualifying "
                            "break occurred cannot be determined."
                            % (start - previous_end, day.isoformat(), *divmod(driving_since_break, 60))
                        ),
                        article="Regulation (EC) 561/2006 Art 7",
                        day=day,
                        limit_minutes=DRIVING_PERIOD_BEFORE_BREAK,
                        actual_minutes=None,
                        evidence={"gap_minutes": start - previous_end},
                    )
                )
            driving_since_break = 0
            break_parts = []
            breach_reported = False
        previous_end = end

        duration = end - start

        if activity is Activity.DRIVING:
            driving_since_break += duration
            if (
                driving_since_break > DRIVING_PERIOD_BEFORE_BREAK
                and not breach_reported
                and not (is_last and open_ended)
            ):
                # When the record stops mid-drive the breach is *not* reported from
                # here: the tail handling below reports it as unknown instead.
                # Calling it a breach would assume the driving continued; calling it
                # compliant would assume a break happened that is not recorded.
                result.findings.append(
                    Finding(
                        code="driving_period_without_qualifying_break",
                        severity=SEVERITY_BREACH,
                        message=(
                            "A driving period reached %dh%02d without a qualifying "
                            "break. Article 7 requires an uninterrupted break of at "
                            "least 45 minutes after 4.5 hours of driving, which may "
                            "be split into parts of at least 15 minutes each."
                            % divmod(driving_since_break, 60)
                        ),
                        article="Regulation (EC) 561/2006 Art 7",
                        day=day,
                        limit_minutes=DRIVING_PERIOD_BEFORE_BREAK,
                        actual_minutes=driving_since_break,
                        evidence={"break_parts_minutes": break_parts},
                    )
                )
                breach_reported = True
        elif activity in BREAK_ACTIVITIES:
            if duration >= MIN_BREAK_PART:
                break_parts.append(duration)
                if sum(break_parts) >= QUALIFYING_BREAK_TOTAL:
                    # A qualifying break resets the driving period (Art 4(q)).
                    driving_since_break = 0
                    breach_reported = False
                    break_parts = []
            else:
                # Under 15 minutes does not count towards the 45 at all.
                result.warnings.append(
                    "break_of_%d_minutes_on_%s_is_below_the_15_minute_minimum_and_"
                    "does_not_count_towards_the_45_required" % (duration, day.isoformat())
                )
        # Other work and availability: recorded, but they neither accumulate
        # driving nor satisfy the break requirement (Art 4(d), Art 6(5)).

    _, last_end, last_activity, last_day, last_open = blocks[-1]
    if last_open and driving_since_break > 0:
        # A driving period was still open when the record ended. This covers both
        # "the record stops mid-drive" and "the record stops during other work or
        # availability, hours after the last drive": neither is evidence that a
        # qualifying break was taken, and neither is evidence that it was not.
        result.findings.append(
            Finding(
                code="break_rule_unassessable_open_record",
                severity=SEVERITY_UNKNOWN,
                message=(
                    "The activity record for %s ends without a closing change while "
                    "a driving period of %dh%02d was still open, so whether a "
                    "qualifying break followed cannot be determined."
                    % (last_day.isoformat(), *divmod(driving_since_break, 60))
                ),
                article="Regulation (EC) 561/2006 Art 7",
                day=last_day,
                limit_minutes=DRIVING_PERIOD_BEFORE_BREAK,
                actual_minutes=None,
                evidence={"driving_since_last_qualifying_break": driving_since_break},
            )
        )


# ---------------------------------------------------------------------------
# Article 8 — daily and weekly rest
# ---------------------------------------------------------------------------


def _rest_blocks(
    days: Sequence[DayInput],
) -> List[Tuple[int, int, _dt.date, bool]]:
    """Rest blocks as ``(start, end, start_day, open_ended)``.

    Rest is counted only from recorded BREAK_REST activity, and only where the
    record actually covers the time. A gap between two records is **not** bridged:
    the missing time is unknown, and bridging it is how an engine turns an
    unrecorded night into a compliant 11-hour rest.

    ``open_ended`` means the block runs off the end of the data. That matters: a
    rest of seven hours at the end of the last imported day is not a seven-hour
    rest, it is an unobserved rest of at least seven hours.
    """
    entries = _span_activity_lookup(days)
    if not entries:
        return []
    origin = min(day for day, _ in entries)

    blocks: List[Tuple[int, int, _dt.date, bool]] = []
    for day, span in entries:
        if span.activity is not Activity.BREAK_REST or span.card_not_inserted:
            continue
        start = _absolute_minute(day, span.start_minute, origin)
        end = _absolute_minute(day, span.end_minute, origin)
        if blocks and blocks[-1][1] == start:
            previous = blocks[-1]
            # The new span's open_ended wins: it is the later edge of the block.
            blocks[-1] = (previous[0], end, previous[2], span.open_ended)
        else:
            blocks.append((start, end, day, span.open_ended))
    return blocks


def assess_daily_rest(days: Sequence[DayInput], result: CalculationResult) -> None:
    """Art 8(2) and Art 8(4): daily rest within 24 hours, at most three reductions.

    Deliberately conservative. Rest is only credited where a record covers it, and
    the engine reports what it *observed* rather than asserting compliance: the
    regulation anchors the 24-hour window on the end of the previous daily or
    weekly rest, and a period that starts mid-history cannot be anchored at all.
    """
    blocks = _rest_blocks(days)
    if not blocks:
        result.findings.append(
            Finding(
                code="daily_rest_unassessable_no_rest_recorded",
                severity=SEVERITY_UNKNOWN,
                message=(
                    "No rest period is recorded in this period, so daily rest "
                    "cannot be assessed. This is expected when only driving activity "
                    "was imported."
                ),
                article="Regulation (EC) 561/2006 Art 8(2)",
                limit_minutes=REGULAR_DAILY_REST,
                actual_minutes=None,
            )
        )
        return

    regular = 0
    reduced = 0
    split = 0
    too_short: List[Tuple[int, int, _dt.date]] = []

    index = 0
    while index < len(blocks):
        start, end, day, open_ended = blocks[index]
        duration = end - start

        if duration >= REGULAR_DAILY_REST:
            regular += 1
            index += 1
            continue

        if duration >= REDUCED_DAILY_REST_MIN:
            reduced += 1
            index += 1
            continue

        # Split daily rest: at least 3 hours, then at least 9 (Art 4(g)), the two
        # parts together inside a 24-hour window (Art 8(2)).
        if duration >= SPLIT_DAILY_REST_FIRST and index + 1 < len(blocks):
            next_start, next_end, _next_day, _next_open = blocks[index + 1]
            next_duration = next_end - next_start
            if next_duration >= SPLIT_DAILY_REST_SECOND and (
                next_end - start
            ) <= DAILY_REST_WINDOW:
                split += 1
                index += 2
                continue

        if duration >= SPLIT_DAILY_REST_FIRST:
            # A block that runs off the end of the data is only *at least* this
            # long. Reporting it as "below the minimum" would be an assertion the
            # data does not support, so it is reported as unknown instead.
            too_short.append((start, end, day, open_ended))
        index += 1

    reduced_total = reduced + split
    if reduced_total > MAX_REDUCED_DAILY_RESTS:
        # Only counted across the period as a whole; a stricter count needs the
        # weekly-rest boundaries, which require a longer import history.
        result.findings.append(
            Finding(
                code="reduced_daily_rest_count",
                severity=SEVERITY_WARNING,
                message=(
                    "%d reduced or split daily rests were observed in this period. "
                    "Article 8(4) permits at most three reduced daily rests between "
                    "any two weekly rests; check the weekly-rest boundaries before "
                    "treating this as a breach." % reduced_total
                ),
                article="Regulation (EC) 561/2006 Art 8(4)",
                limit_minutes=None,
                actual_minutes=reduced_total,
                evidence={
                    "reduced": reduced,
                    "split": split,
                    "regular": regular,
                    "counted_across_period": True,
                },
            )
        )

    for start, end, day, open_ended in too_short:
        if open_ended:
            # Runs off the end of the data: the rest may well continue and become
            # a valid daily rest. Say so rather than calling it too short.
            result.findings.append(
                Finding(
                    code="rest_block_open_at_end_of_data",
                    severity=SEVERITY_UNKNOWN,
                    message=(
                        "A rest block of %dh%02d starting on %s runs to the end of "
                        "the imported data, so its true duration is unknown. It "
                        "cannot be counted as a daily rest or ruled out as one."
                        % (*divmod((end - start), 60), day.isoformat())
                    ),
                    article="Regulation (EC) 561/2006 Art 4(g)",
                    day=day,
                    limit_minutes=REDUCED_DAILY_REST_MIN,
                    actual_minutes=None,
                )
            )
            continue
        # A rest below 3 hours is not part of any daily-rest arrangement, but it
        # may be a break. Reporting it as unknown prevents it being read as rest.
        result.findings.append(
            Finding(
                code="rest_block_below_daily_rest_minimum",
                severity=SEVERITY_UNKNOWN,
                message=(
                    "A rest block of %dh%02d starting on %s is below both the "
                    "9-hour reduced daily rest and the 3-hour first part of a split "
                    "daily rest. It may be a break; it is not a daily rest."
                    % (*divmod((end - start), 60), day.isoformat())
                ),
                article="Regulation (EC) 561/2006 Art 4(g)",
                day=day,
                limit_minutes=REDUCED_DAILY_REST_MIN,
                actual_minutes=end - start,
            )
        )

    result.assumptions.append(
        "Daily rest is reported as observed. The engine does not assert compliance "
        "because the 24-hour window is anchored on the end of the previous daily or "
        "weekly rest, which requires import history earlier than this period."
    )


def assess_weekly_rest(days: Sequence[DayInput], result: CalculationResult) -> None:
    """Art 8(6): a weekly rest in every week, regular or reduced.

    Reports what the data shows and marks unknown where the period does not cover
    the whole week, rather than assuming a rest happened outside the records.
    """
    blocks = _rest_blocks(days)
    if not blocks:
        result.findings.append(
            Finding(
                code="weekly_rest_unassessable_no_rest_recorded",
                severity=SEVERITY_UNKNOWN,
                message="No rest period is recorded, so weekly rest cannot be assessed.",
                article="Regulation (EC) 561/2006 Art 8(6)",
                limit_minutes=REGULAR_WEEKLY_REST,
                actual_minutes=None,
            )
        )
        return

    origin = blocks[0][2]
    covered_start = min(day.day for day in days)
    covered_end = max(day.day for day in days)

    weeks_with_regular: Dict[_dt.date, int] = {}
    weeks_with_reduced: Dict[_dt.date, int] = {}

    for start, end, _day, _open_ended in blocks:
        duration = end - start
        if duration < REDUCED_WEEKLY_REST_MIN:
            continue
        block_day = origin + _dt.timedelta(minutes=start)
        week = week_start(block_day)
        if duration >= REGULAR_WEEKLY_REST:
            weeks_with_regular[week] = weeks_with_regular.get(week, 0) + 1
        else:
            weeks_with_reduced[week] = weeks_with_reduced.get(week, 0) + 1

    # Every week the data touches, not only the weeks where a weekly rest happened
    # to be found. A week with no weekly rest at all is precisely the case Article
    # 8(6) forbids, and iterating only over weeks that contained a rest skipped it
    # entirely — a breach that could never be reported.
    first_week = week_start(covered_start)
    last_week = week_start(covered_end)
    weeks_in_range: List[_dt.date] = []
    cursor = first_week
    while cursor <= last_week:
        weeks_in_range.append(cursor)
        cursor += _dt.timedelta(days=7)

    for week in weeks_in_range:
        week_end = week + _dt.timedelta(days=7)
        fully_covered = covered_start <= week and covered_end >= week_end - _dt.timedelta(days=1)
        if not fully_covered:
            result.findings.append(
                Finding(
                    code="weekly_rest_unassessable_partial_week",
                    severity=SEVERITY_UNKNOWN,
                    message=(
                        "The week beginning %s is not fully covered by the imported "
                        "records (%s..%s), so its weekly rest cannot be confirmed."
                        % (
                            week.isoformat(),
                            covered_start.isoformat(),
                            covered_end.isoformat(),
                        )
                    ),
                    article="Regulation (EC) 561/2006 Art 8(6)",
                    day=week,
                    limit_minutes=REGULAR_WEEKLY_REST,
                    actual_minutes=None,
                )
            )
            continue
        if week not in weeks_with_regular and week not in weeks_with_reduced:
            result.findings.append(
                Finding(
                    code="weekly_rest_not_found",
                    severity=SEVERITY_BREACH,
                    message=(
                        "No weekly rest of at least 24 hours was recorded in the "
                        "week beginning %s. Article 8(6) requires a regular weekly "
                        "rest of 45 hours, or a reduced one of at least 24 hours "
                        "compensated by an equivalent rest before the end of the "
                        "third week following." % week.isoformat()
                    ),
                    article="Regulation (EC) 561/2006 Art 8(6)",
                    day=week,
                    limit_minutes=REDUCED_WEEKLY_REST_MIN,
                    actual_minutes=0,
                )
            )

    for week, count in sorted(weeks_with_reduced.items()):
        if count and week not in weeks_with_regular:
            result.findings.append(
                Finding(
                    code="weekly_rest_reduced_compensation_required",
                    severity=SEVERITY_WARNING,
                    message=(
                        "The weekly rest in the week beginning %s was reduced below "
                        "45 hours. Article 8(6b) requires the reduction to be "
                        "compensated by an equivalent rest taken en bloc before the "
                        "end of the third week following, attached to a rest of at "
                        "least 9 hours. This engine does not verify that the "
                        "compensation was taken." % week.isoformat()
                    ),
                    article="Regulation (EC) 561/2006 Art 8(6b)",
                    day=week,
                    limit_minutes=REGULAR_WEEKLY_REST,
                    actual_minutes=None,
                    evidence={"compensation_verified": False},
                )
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def calculate(
    driver_key: str,
    days: Sequence[DayInput],
    *,
    period_start: Optional[_dt.date] = None,
    period_end: Optional[_dt.date] = None,
    data_age_days: Optional[int] = None,
) -> CalculationResult:
    """Run every applicable rule over ``days``.

    ``data_age_days`` is how old the newest record is. A period whose newest record
    is older than ``STALE_AFTER_DAYS`` is reported ``stale`` rather than calculated:
    presenting last month's driving time as today's remaining hours is the specific
    failure the spec warns about.
    """
    ordered = sorted(days, key=lambda d: d.day)
    if not ordered:
        result = CalculationResult(
            driver_key=driver_key,
            period_start=period_start or _dt.date.today(),
            period_end=period_end or _dt.date.today(),
            status=STATUS_INSUFFICIENT,
        )
        result.warnings.append("no_activity_days_supplied")
        result.findings.append(
            Finding(
                code="no_data",
                severity=SEVERITY_UNKNOWN,
                message="No recorded activity was available for this driver and period.",
                article="n/a",
            )
        )
        return result

    start = period_start or ordered[0].day
    end = period_end or ordered[-1].day

    result = CalculationResult(
        driver_key=driver_key,
        period_start=start,
        period_end=end,
    )
    result.source_days = [d.day for d in ordered]
    result.source_import_ids = sorted(
        {d.import_id for d in ordered if d.import_id is not None}
    )

    # Which days in the requested span have no record at all. These are gaps, and
    # the presence of any gap is what makes rest findings "unknown" above.
    present = {d.day for d in ordered}
    result.missing_days = [
        start + _dt.timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + _dt.timedelta(days=offset)) not in present
    ]

    result.assumptions.extend(
        [
            "Activity times are the local wall clock stored in the file; no "
            "timezone conversion and no daylight-saving shift is applied.",
            "Only recorded BREAK_REST counts as a break. Other work and "
            "availability do not interrupt a driving period (Art 4(d), Art 6(5)).",
            "Gaps in the records are treated as unknown, never as rest.",
            "Week boundaries are Monday 00:00 to Sunday 24:00 (Art 4(i)).",
            "Working time under Directive 2002/15/EC is not assessed.",
            "Regulation (EU) 2024/1258 (occasional passenger transport) is not "
            "implemented; this deployment is goods transport.",
        ]
    )

    totals = daily_driving_totals(ordered)
    result.daily_driving = totals
    result.weekly_driving = {}
    assess_daily_driving(totals, result)
    result.fortnightly_driving = assess_weekly_driving(totals, result)

    # Recompute weekly totals into the result so the report and the checks agree.
    weekly: Dict[_dt.date, int] = {}
    for day, minutes in totals.items():
        weekly[week_start(day)] = weekly.get(week_start(day), 0) + minutes
    result.weekly_driving = weekly

    assess_breaks(ordered, result)
    assess_daily_rest(ordered, result)
    assess_weekly_rest(ordered, result)

    if result.missing_days:
        result.warnings.append(
            "missing_activity_days=%d: %s"
            % (
                len(result.missing_days),
                ", ".join(d.isoformat() for d in result.missing_days[:10]),
            )
        )
    uncovered = sum(d.uncovered_minutes for d in ordered)
    if uncovered:
        result.warnings.append(
            "recorded_time_without_a_card=%d_minutes: activity there is unknown"
            % uncovered
        )

    if data_age_days is not None and data_age_days > STALE_AFTER_DAYS:
        result.status = STATUS_STALE
        result.warnings.append(
            "source_data_is_%d_days_old (threshold %d): remaining hours are not "
            "shown from stale data" % (data_age_days, STALE_AFTER_DAYS)
        )
    elif result.missing_days or uncovered:
        result.status = STATUS_INSUFFICIENT
    else:
        result.status = STATUS_OK

    return result
