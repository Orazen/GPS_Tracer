"""Domain model for tachograph activity.

Pure standard library, deliberately. The parser, this model and the rules engine
must be testable with no third-party package installed, because they are the
part of the system that decides whether somebody's driving hours are right.

The one thing to hold on to while reading this: an ``ActivityChange`` is
**recorded history** — a fact read out of a file. A driving-time limit is a
**calculation** derived from that history under a named rules version. The two
are never mixed, and nothing here ever represents the second as if it were the
first.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, List, Optional, Sequence, Tuple

UTC = _dt.timezone.utc


class Activity(IntEnum):
    """The four activities a tachograph records.

    Values are the on-file codes (``aa`` in ``ActivityChangeInfo``), not an
    arbitrary enumeration: ``BREAK_REST`` is 0 because the file says 0. Do not
    renumber these.
    """

    BREAK_REST = 0
    AVAILABILITY = 1
    WORK = 2
    DRIVING = 3

    @property
    def label_it(self) -> str:
        return {
            Activity.BREAK_REST: "Riposo/Interruzione",
            Activity.AVAILABILITY: "Disponibilità",
            Activity.WORK: "Altro lavoro",
            Activity.DRIVING: "Guida",
        }[self]

    @property
    def label_en(self) -> str:
        return {
            Activity.BREAK_REST: "Break/rest",
            Activity.AVAILABILITY: "Availability",
            Activity.WORK: "Other work",
            Activity.DRIVING: "Driving",
        }[self]


@dataclass(frozen=True)
class ActivityChange:
    """One ``ActivityChangeInfo`` word, decoded.

    ``minute_of_day`` is minutes since 00:00 on ``day``, as stored. It is *not*
    converted to UTC here: tachograph activity is wall-clock local time of the
    vehicle, and silently shifting it would corrupt every downstream total.
    """

    day: _dt.date
    minute_of_day: int
    activity: Activity
    slot: int = 0            # 0 driver, 1 co-driver
    crew: bool = False       # 'c' bit: driving in a crew
    card_not_inserted: bool = False   # 'p' bit

    @property
    def is_driver_slot(self) -> bool:
        return self.slot == 0

    def as_local_datetime(self, tz: _dt.tzinfo) -> _dt.datetime:
        """Midnight-of-day plus minutes, in a named timezone."""
        naive = _dt.datetime.combine(self.day, _dt.time(0, 0)) + _dt.timedelta(
            minutes=self.minute_of_day
        )
        return naive.replace(tzinfo=tz)


@dataclass(frozen=True)
class ActivityDay:
    """A ``CardActivityDailyRecord``: one calendar day of activity."""

    day: _dt.date
    presence_counter: Optional[int]
    distance_km: Optional[int]
    changes: Tuple[ActivityChange, ...] = ()

    def driver_changes(self) -> Tuple[ActivityChange, ...]:
        """Changes that apply to the driver slot, ordered by time.

        Co-driver activity is stored in the same record and shares the same
        timeline. Totals for "the driver" must not include co-driver rows, but
        multi-manning *does* change which limits apply — so the co-driver rows
        are kept and passed to the rules engine rather than discarded.
        """
        return tuple(
            sorted(
                (c for c in self.changes if c.is_driver_slot),
                key=lambda c: c.minute_of_day,
            )
        )

    def co_driver_changes(self) -> Tuple[ActivityChange, ...]:
        return tuple(
            sorted(
                (c for c in self.changes if not c.is_driver_slot),
                key=lambda c: c.minute_of_day,
            )
        )


@dataclass(frozen=True)
class ActivitySpan:
    """A continuous stretch of one activity, built from consecutive changes.

    ``end`` is exclusive. ``open_ended`` means the span runs to the end of the
    record with no terminating change: the file simply stops. That is common on
    the most recent day, and it must not be read as "rest until midnight".
    """

    activity: Activity
    start_minute: int
    end_minute: int
    open_ended: bool = False
    card_not_inserted: bool = False

    @property
    def duration_minutes(self) -> int:
        return max(0, self.end_minute - self.start_minute)


@dataclass
class DayTotals:
    """Recorded minutes per activity for one day. Not a compliance finding."""

    day: _dt.date
    minutes: Dict[Activity, int] = field(default_factory=dict)
    uncovered_minutes: int = 0
    """Minutes with no activity recorded (card withdrawn, or record gap)."""
    open_ended: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def total_recorded(self) -> int:
        return sum(self.minutes.values())

    def minutes_of(self, activity: Activity) -> int:
        return self.minutes.get(activity, 0)


def build_spans(day: ActivityDay, slot_driver: bool = True) -> List[ActivitySpan]:
    """Turn a day's changes into contiguous spans.

    Deliberately conservative, three rules:

    1. The record is assumed to begin at 00:00 with the first change's activity.
       The specification requires the set to include the 00:00 entry, so this
       holds for a well-formed file.
    2. A change with ``card_not_inserted`` starts an uncovered span, not a
       break. Driving time cannot be inferred from a period with no card.
    3. The final span ends at 24:00 and is flagged ``open_ended``, because the
       file gives no closing change.
    """
    changes = day.driver_changes() if slot_driver else day.co_driver_changes()
    if not changes:
        return []

    spans: List[ActivitySpan] = []
    for index, change in enumerate(changes):
        next_change = changes[index + 1] if index + 1 < len(changes) else None
        end_minute = next_change.minute_of_day if next_change else 24 * 60
        if end_minute <= change.minute_of_day:
            # Non-monotonic file. Skip rather than emit a zero or negative span.
            continue
        spans.append(
            ActivitySpan(
                activity=change.activity,
                start_minute=change.minute_of_day,
                end_minute=end_minute,
                open_ended=next_change is None,
                card_not_inserted=change.card_not_inserted,
            )
        )
    return spans


def summarise_day(day: ActivityDay, slot_driver: bool = True) -> DayTotals:
    """Per-activity minute totals for one day, with gaps made explicit."""
    totals = DayTotals(day=day.day)
    spans = build_spans(day, slot_driver=slot_driver)
    if not spans:
        totals.warnings.append("no_activity_recorded")
        totals.uncovered_minutes = 24 * 60
        return totals

    # Any time before the first change is unaccounted for.
    first = spans[0]
    if first.start_minute > 0:
        totals.uncovered_minutes += first.start_minute

    for span in spans:
        if span.card_not_inserted:
            totals.uncovered_minutes += span.duration_minutes
            continue
        totals.minutes[span.activity] = (
            totals.minutes.get(span.activity, 0) + span.duration_minutes
        )

    if any(span.open_ended for span in spans):
        totals.open_ended = True
        totals.warnings.append(
            "last_span_open_ended: the record stops without a closing change; "
            "its duration is not evidence of rest"
        )
    if totals.uncovered_minutes:
        totals.warnings.append(
            "card_not_inserted_minutes=%d: activity for that period is unknown"
            % totals.uncovered_minutes
        )
    return totals


def summarise_days(
    days: Sequence[ActivityDay], slot_driver: bool = True
) -> List[DayTotals]:
    return [summarise_day(day, slot_driver=slot_driver) for day in days]


def sort_unique_days(days: Sequence[ActivityDay]) -> List[ActivityDay]:
    """De-duplicate days, keeping the one with the most changes.

    A card that was downloaded twice, or a card session that overlaps a VU
    download, legitimately produces two records for the same date. Keeping the
    fuller record is the least-surprising choice; merging them would invent
    activity that neither source recorded.
    """
    best: Dict[_dt.date, ActivityDay] = {}
    for day in days:
        current = best.get(day.day)
        if current is None or len(day.changes) > len(current.changes):
            best[day.day] = day
    return [best[key] for key in sorted(best)]
