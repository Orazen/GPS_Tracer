"""Driver registry and assignments -- the writes.

`repository.py` answers questions about what was recorded. This module is the
only place that changes **who is linked to what**, and it is separate for the
same reason the read queries are: every statement here changes evidence about a
person, and the rules that make those changes safe are easier to review in one
file than scattered through route handlers.

Nothing here deletes a row. A closed assignment is history, and history is what
makes "who was driving that truck on the 3rd" answerable -- including for a date
before somebody's card was replaced.

Three invariants, and where each one is enforced:

* **A driver has at most one open vehicle assignment.** Enforced twice: by this
  module, which closes the previous row, and by a partial unique index
  (`0004_assignment_invariants.sql`), because a module that only *remembers* to
  close the previous row is one refactor away from two open rows.
* **A card belongs to one person at a time, and a person holds one open card.**
  Same two places.
* **A vehicle may have more than one open assignment.** Art 8(5) multi-manning
  puts two drivers in the same cab, so the correct case has to stay recordable;
  there is no unique index on the vehicle side on purpose. Reading either open
  row answers "who is in this truck", and there may be two answers.

Closing uses `GREATEST(assigned_from, <new start - 1 day>)` rather than the plain
end date. A reassignment on the same day the previous one started would otherwise
try to close a row before it opened and trip the table's own CHECK constraint; the
`GREATEST` closes it on the day it started, which is the only value that both
satisfies the constraint and leaves exactly one row open.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Dict, List, Optional, Sequence

from .db import Database

PEOPLE_COLUMNS = ("id", "display_name", "external_ref", "active", "created_at")

ASSIGNMENT_COLUMNS = (
    "id",
    "driver_id",
    "vehicle_ref",
    "assigned_from",
    "assigned_to",
    "note",
    "created_at",
)

CARD_ASSIGNMENT_COLUMNS = (
    "id",
    "driver_id",
    "card_number",
    "assigned_from",
    "assigned_to",
    "note",
    "created_at",
)

MAX_NAME = 120
MAX_VEHICLE_REF = 120


class RegistryError(Exception):
    """Base class for the failures a caller can be told about."""


class UnknownDriver(RegistryError):
    pass


class UnknownCard(RegistryError):
    pass


class DuplicateExternalRef(RegistryError):
    pass


class InvalidAssignment(RegistryError):
    pass


def _clean(value: Optional[str], field: str, limit: int) -> Optional[str]:
    if value is None:
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > limit:
        raise InvalidAssignment("%s is longer than %d characters" % (field, limit))
    return text


class DriverRegistry:
    def __init__(self, db: Database) -> None:
        self.db = db

    # -- people ----------------------------------------------------------
    def list_people(self) -> List[Dict[str, Any]]:
        """Every registered person, with whatever they are holding right now.

        LEFT JOINs, not INNER: a person with no card and no vehicle is a normal
        state -- a new hire, or somebody who has just handed a truck back -- and
        must still appear, or the console cannot show them to be assigned.
        """
        rows = self.db.fetch_all(
            """
            SELECT d.id, d.display_name, d.external_ref, d.active, d.created_at,
                   c.card_number, c.assigned_from AS card_from,
                   a.id AS assignment_id, a.vehicle_ref,
                   a.assigned_from AS vehicle_from, a.note
              FROM tacho_drivers d
              LEFT JOIN tacho_card_assignments c
                     ON c.driver_id = d.id AND c.assigned_to IS NULL
              LEFT JOIN tacho_vehicle_assignments a
                     ON a.driver_id = d.id AND a.assigned_to IS NULL
             ORDER BY d.active DESC, d.display_name
            """
        )
        keys = (
            "id", "display_name", "external_ref", "active", "created_at",
            "card_number", "card_from", "assignment_id", "vehicle_ref",
            "vehicle_from", "note",
        )
        return [dict(zip(keys, row)) for row in rows]

    def get_person(self, driver_id: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetch_one(
            "SELECT %s FROM tacho_drivers WHERE id = %%s" % ", ".join(PEOPLE_COLUMNS),
            (driver_id,),
        )
        return dict(zip(PEOPLE_COLUMNS, row)) if row else None

    def find_person_by_external_ref(self, external_ref: str) -> Optional[Dict[str, Any]]:
        row = self.db.fetch_one(
            "SELECT %s FROM tacho_drivers WHERE external_ref = %%s"
            % ", ".join(PEOPLE_COLUMNS),
            (external_ref,),
        )
        return dict(zip(PEOPLE_COLUMNS, row)) if row else None

    def create_person(
        self, display_name: str, external_ref: Optional[str] = None
    ) -> Dict[str, Any]:
        name = _clean(display_name, "display_name", MAX_NAME)
        if not name:
            raise InvalidAssignment("display_name is required")
        ref = _clean(external_ref, "external_ref", MAX_NAME)
        if ref and self.find_person_by_external_ref(ref):
            # Caught here for the message, and not only here: the index in 0002
            # is what actually guarantees it.
            raise DuplicateExternalRef("a person already uses external_ref '%s'" % ref)
        row = self.db.fetch_one(
            """
            INSERT INTO tacho_drivers (display_name, external_ref)
            VALUES (%%s, %%s)
            RETURNING %s
            """ % ", ".join(PEOPLE_COLUMNS),
            (name, ref),
        )
        return dict(zip(PEOPLE_COLUMNS, row))

    def set_active(self, driver_id: int, active: bool) -> Dict[str, Any]:
        row = self.db.fetch_one(
            "UPDATE tacho_drivers SET active = %%s WHERE id = %%s RETURNING %s"
            % ", ".join(PEOPLE_COLUMNS),
            (bool(active), driver_id),
        )
        if row is None:
            raise UnknownDriver("no person with id %s" % driver_id)
        return dict(zip(PEOPLE_COLUMNS, row))

    # -- card links ------------------------------------------------------
    def list_card_assignments(
        self, driver_id: Optional[int] = None, limit: int = 200
    ) -> List[Dict[str, Any]]:
        columns = ", ".join("ca." + c for c in CARD_ASSIGNMENT_COLUMNS)
        if driver_id is None:
            rows = self.db.fetch_all(
                "SELECT %s FROM tacho_card_assignments ca "
                "ORDER BY ca.assigned_from DESC, ca.id DESC LIMIT %%s" % columns,
                (min(max(limit, 1), 500),),
            )
        else:
            rows = self.db.fetch_all(
                "SELECT %s FROM tacho_card_assignments ca WHERE ca.driver_id = %%s "
                "ORDER BY ca.assigned_from DESC, ca.id DESC LIMIT %%s" % columns,
                (driver_id, min(max(limit, 1), 500)),
            )
        return [dict(zip(CARD_ASSIGNMENT_COLUMNS, row)) for row in rows]

    def assign_card(
        self,
        driver_id: int,
        card_number: str,
        assigned_from: Optional[_dt.date] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Put a card in a person's hand, closing the open claims it replaces.

        Two claims are closed, not one: the person's own open card (they cannot
        hold two) and any other person's open claim on this card (a card cannot be
        in two hands). Both are the same day rule as a vehicle assignment.
        """
        card = _clean(card_number, "card_number", 64)
        if not card:
            raise InvalidAssignment("card_number is required")
        if self.get_person(driver_id) is None:
            raise UnknownDriver("no person with id %s" % driver_id)
        if self.db.fetch_one(
            "SELECT 1 FROM tacho_driver_cards WHERE card_number = %s", (card,)
        ) is None:
            # The registry of cards is built by imports. Linking a card that has
            # never been seen would create a reference to nothing.
            raise UnknownCard("card '%s' is not in the card registry; import it first" % card)

        start = assigned_from or _dt.date.today()
        ends = start - _dt.timedelta(days=1)
        connection = self.db.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tacho_card_assignments
                       SET assigned_to = GREATEST(assigned_from, %s)
                     WHERE assigned_to IS NULL
                       AND (driver_id = %s OR card_number = %s)
                    """,
                    (ends, driver_id, card),
                )
                cursor.execute(
                    """
                    INSERT INTO tacho_card_assignments
                        (driver_id, card_number, assigned_from, note)
                    VALUES (%%s, %%s, %%s, %%s)
                    RETURNING %s
                    """ % ", ".join(CARD_ASSIGNMENT_COLUMNS),
                    (driver_id, card, start, _clean(note, "note", 500)),
                )
                row = cursor.fetchone()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return dict(zip(CARD_ASSIGNMENT_COLUMNS, row))

    # -- vehicle assignments ---------------------------------------------
    def list_vehicle_assignments(
        self,
        driver_id: Optional[int] = None,
        vehicle_ref: Optional[str] = None,
        limit: int = 200,
    ) -> List[Dict[str, Any]]:
        clauses: List[str] = []
        params: List[Any] = []
        if driver_id is not None:
            clauses.append("driver_id = %s")
            params.append(driver_id)
        if vehicle_ref:
            clauses.append("vehicle_ref = %s")
            params.append(vehicle_ref)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.db.fetch_all(
            """
            SELECT %s FROM tacho_vehicle_assignments%s
             ORDER BY assigned_to IS NULL DESC, assigned_from DESC, id DESC
             LIMIT %%s
            """
            % (", ".join(ASSIGNMENT_COLUMNS), where),
            tuple(params) + (min(max(limit, 1), 500),),
        )
        return [dict(zip(ASSIGNMENT_COLUMNS, row)) for row in rows]

    def assign_vehicle(
        self,
        driver_id: int,
        vehicle_ref: str,
        assigned_from: Optional[_dt.date] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Put a driver in a vehicle, closing that driver's open assignment.

        Only the **driver's** previous assignment is closed. The vehicle's open
        assignments are left alone: if two drivers are recorded in the same truck
        (multi-manning), assigning a third must not silently end the other two --
        whoever ends those says so explicitly, by assigning them elsewhere.
        """
        vehicle = _clean(vehicle_ref, "vehicle_ref", MAX_VEHICLE_REF)
        if not vehicle:
            raise InvalidAssignment("vehicle_ref is required")
        if self.get_person(driver_id) is None:
            raise UnknownDriver("no person with id %s" % driver_id)

        start = assigned_from or _dt.date.today()
        ends = start - _dt.timedelta(days=1)
        connection = self.db.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE tacho_vehicle_assignments
                       SET assigned_to = GREATEST(assigned_from, %s)
                     WHERE driver_id = %s AND assigned_to IS NULL
                    """,
                    (ends, driver_id),
                )
                cursor.execute(
                    """
                    INSERT INTO tacho_vehicle_assignments
                        (driver_id, vehicle_ref, assigned_from, note)
                    VALUES (%%s,%%s,%%s,%%s)
                    RETURNING %s
                    """ % ", ".join(ASSIGNMENT_COLUMNS),
                    (driver_id, vehicle, start, _clean(note, "note", 500)),
                )
                row = cursor.fetchone()
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        return dict(zip(ASSIGNMENT_COLUMNS, row))

    def close_vehicle_assignment(
        self, assignment_id: int, assigned_to: Optional[_dt.date] = None
    ) -> Dict[str, Any]:
        """End an open assignment on a chosen date. The only way a driver leaves
        a truck without another one being named."""
        end = assigned_to or _dt.date.today()
        row = self.db.fetch_one(
            """
            UPDATE tacho_vehicle_assignments
               SET assigned_to = GREATEST(assigned_from, %%s)
             WHERE id = %%s AND assigned_to IS NULL
            RETURNING %s
            """ % ", ".join(ASSIGNMENT_COLUMNS),
            (end, assignment_id),
        )
        if row is None:
            raise InvalidAssignment(
                "assignment %s is not open (or does not exist), so there is nothing to close"
                % assignment_id
            )
        return dict(zip(ASSIGNMENT_COLUMNS, row))


def open_vehicle_of(people: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    """vehicle_ref -> driver names currently recorded in it.

    A list, not a name: multi-manning means a truck can legitimately have two.
    """
    out: Dict[str, List[str]] = {}
    for person in people:
        ref = person.get("vehicle_ref")
        if ref:
            out.setdefault(ref, []).append(person["display_name"])
    return out
