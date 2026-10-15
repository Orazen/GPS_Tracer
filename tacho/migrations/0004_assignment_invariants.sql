-- ---------------------------------------------------------------------------
-- 0004_assignment_invariants.sql — one open assignment per driver, one open card
--
-- 0002 created the assignment tables. Nothing has written to them until now, so
-- these indexes apply to empty tables; they exist because "close the previous
-- one" is a rule a route handler can forget, and two open assignments for the
-- same driver is not a cosmetic problem -- it makes "who is driving that truck"
-- have two answers, and a driver cannot be in two cabs.
--
-- A partial unique index is the only way to say this in SQL: the constraint is
-- on the OPEN rows (assigned_to IS NULL), while the closed rows are history and
-- must accumulate freely.
-- ---------------------------------------------------------------------------

-- A driver is in one vehicle at a time.
CREATE UNIQUE INDEX IF NOT EXISTS tacho_vehicle_assignments_one_open_per_driver
    ON tacho_vehicle_assignments (driver_id)
    WHERE assigned_to IS NULL;

-- A card is in one person's hand at a time...
CREATE UNIQUE INDEX IF NOT EXISTS tacho_card_assignments_one_open_per_card
    ON tacho_card_assignments (card_number)
    WHERE assigned_to IS NULL;

-- ...and a person holds one open card at a time.
CREATE UNIQUE INDEX IF NOT EXISTS tacho_card_assignments_one_open_per_driver
    ON tacho_card_assignments (driver_id)
    WHERE assigned_to IS NULL;

-- Deliberately NOT indexed: an open assignment per vehicle_ref. A truck with two
-- drivers in it is a legitimate, regulated case -- Art 8(5) multi-manning -- and a
-- unique index here would make the correct case impossible to record. The vehicle
-- side gets a lookup index instead, and the console shows however many open
-- assignments a truck has rather than pretending there can only be one.
CREATE INDEX IF NOT EXISTS tacho_vehicle_assignments_vehicle_idx
    ON tacho_vehicle_assignments (vehicle_ref, assigned_from DESC);
