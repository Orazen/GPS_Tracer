-- ---------------------------------------------------------------------------
-- 0002_drivers.sql — driver-card registry, assignment history, audit log
--
-- A driver card is personal data and the card number is a card identifier: the
-- spec requires both to be protected. They are held here, in the private
-- database, and never in a public URL or a public asset.
-- ---------------------------------------------------------------------------

-- Registry of driver cards seen by this service, one row per card number.
CREATE TABLE IF NOT EXISTS tacho_driver_cards (
    card_number         TEXT        PRIMARY KEY,
    issuing_member_state INTEGER,
    holder_surname      TEXT,
    holder_first_names  TEXT,
    holder_birth_date   DATE,
    issue_date          DATE,
    validity_begin      DATE,
    expiry_date         DATE,
    first_seen_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Drivers as people. Separated from cards because a driver keeps their card when
-- they change employer and can be reissued a card after a replacement. Without
-- this split, "who was driving" becomes unanswerable at the first renewal.
CREATE TABLE IF NOT EXISTS tacho_drivers (
    id                  BIGSERIAL PRIMARY KEY,
    display_name        TEXT        NOT NULL,
    external_ref        TEXT,
    active              BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS tacho_drivers_external_ref_idx
    ON tacho_drivers (external_ref) WHERE external_ref IS NOT NULL;

-- Driver-to-card history. Closed rather than deleted, so a past assignment can
-- still be explained when somebody asks about a date.
CREATE TABLE IF NOT EXISTS tacho_card_assignments (
    id                  BIGSERIAL PRIMARY KEY,
    driver_id           BIGINT      NOT NULL
        REFERENCES tacho_drivers(id) ON DELETE CASCADE,
    card_number         TEXT        NOT NULL
        REFERENCES tacho_driver_cards(card_number) ON DELETE CASCADE,
    assigned_from       DATE        NOT NULL,
    assigned_to         DATE,
    note                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (assigned_to IS NULL OR assigned_to >= assigned_from)
);

CREATE INDEX IF NOT EXISTS tacho_card_assignments_card_idx
    ON tacho_card_assignments (card_number);

-- Driver-to-vehicle history. Vehicle registration is a free-text key because the
-- vehicle registry lives in the tracker domain (Traccar), not here; duplicating
-- it would create two sources of truth for the same truck.
CREATE TABLE IF NOT EXISTS tacho_vehicle_assignments (
    id                  BIGSERIAL PRIMARY KEY,
    driver_id           BIGINT      NOT NULL
        REFERENCES tacho_drivers(id) ON DELETE CASCADE,
    vehicle_ref         TEXT        NOT NULL,
    assigned_from       DATE        NOT NULL,
    assigned_to         DATE,
    note                TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (assigned_to IS NULL OR assigned_to >= assigned_from)
);

CREATE INDEX IF NOT EXISTS tacho_vehicle_assignments_driver_idx
    ON tacho_vehicle_assignments (driver_id, assigned_from DESC);

-- Audit log. Required by the spec for driver-data access, and the reason every
-- read of a driver record is written down before it is returned.
CREATE TABLE IF NOT EXISTS tacho_audit_log (
    id                  BIGSERIAL PRIMARY KEY,
    at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor               TEXT        NOT NULL,
    actor_role          TEXT,
    action              TEXT        NOT NULL,
    subject_type        TEXT,
    subject_id          TEXT,
    detail              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    source_ip           TEXT
);

CREATE INDEX IF NOT EXISTS tacho_audit_log_at_idx ON tacho_audit_log (at DESC);
CREATE INDEX IF NOT EXISTS tacho_audit_log_subject_idx
    ON tacho_audit_log (subject_type, subject_id);
CREATE INDEX IF NOT EXISTS tacho_audit_log_actor_idx ON tacho_audit_log (actor);
