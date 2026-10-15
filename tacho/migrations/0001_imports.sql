-- ---------------------------------------------------------------------------
-- 0001_imports.sql — tachograph imports and normalised activity
--
-- Tables are prefixed tacho_ so they never collide with Traccar's tc_ tables in
-- the same PostgreSQL database. One database, two clearly separated domains;
-- this service only ever reads and writes its own prefix.
--
-- Personal data note: holder_surname / holder_first_names / holder_birth_date and
-- the raw file are personal data under the GDPR. They are stored because a fleet
-- must be able to answer "whose card is this", and the retention policy in
-- docs/SECURITY.md applies. Nothing here is ever served from a public URL.
-- ---------------------------------------------------------------------------

-- Migration ledger. The runner refuses to start if an already-applied migration's
-- checksum no longer matches, so an edited migration is caught rather than
-- silently skipped.
CREATE TABLE IF NOT EXISTS tacho_schema_migrations (
    version     INTEGER PRIMARY KEY,
    name        TEXT        NOT NULL,
    checksum    TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per uploaded file. Also the worker's queue: see claim_pending() below.
CREATE TABLE IF NOT EXISTS tacho_imports (
    id                  BIGSERIAL PRIMARY KEY,
    original_filename   TEXT        NOT NULL,
    content_sha256      CHAR(64)    NOT NULL,
    size_bytes          BIGINT      NOT NULL CHECK (size_bytes > 0),
    uploaded_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    uploaded_by         TEXT,

    -- What the uploader said it is, and what the parser decided it is. Kept
    -- separately: a disagreement is worth showing, not hiding.
    declared_kind       TEXT        NOT NULL DEFAULT 'unknown',
    source_kind         TEXT        NOT NULL DEFAULT 'unknown',
    generation          TEXT        NOT NULL DEFAULT 'unknown',

    status              TEXT        NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'done', 'failed', 'duplicate', 'rejected')),
    attempts            INTEGER     NOT NULL DEFAULT 0,
    claimed_at          TIMESTAMPTZ,
    processed_at        TIMESTAMPTZ,

    parser_name         TEXT,
    parser_version      TEXT,
    error_code          TEXT,
    error_message       TEXT,
    warnings            JSONB       NOT NULL DEFAULT '[]'::jsonb,
    raw_evidence        JSONB       NOT NULL DEFAULT '{}'::jsonb,

    -- Driver-card identity, when the file is a driver card.
    card_number         TEXT,
    issuing_member_state INTEGER,
    holder_surname      TEXT,
    holder_first_names  TEXT,
    holder_birth_date   DATE,
    card_issue_date     DATE,
    card_validity_begin DATE,
    card_expiry_date    DATE,

    -- Where the original file lives on the private volume. A path, never a URL:
    -- the spec forbids exposing originals publicly and this column is the reason
    -- the API has no endpoint that returns it.
    stored_path         TEXT        NOT NULL,

    -- Duplicate detection. Duplicates are kept, not rejected: import history is a
    -- requirement, and "the same card was uploaded twice" is a fact worth having.
    is_duplicate        BOOLEAN     NOT NULL DEFAULT FALSE,
    duplicate_of        BIGINT      REFERENCES tacho_imports(id) ON DELETE SET NULL
);

-- Duplicate lookup is by content hash and must be fast.
CREATE INDEX IF NOT EXISTS tacho_imports_sha256_idx ON tacho_imports (content_sha256);
CREATE INDEX IF NOT EXISTS tacho_imports_uploaded_at_idx
    ON tacho_imports (uploaded_at DESC);
CREATE INDEX IF NOT EXISTS tacho_imports_status_idx ON tacho_imports (status);
CREATE INDEX IF NOT EXISTS tacho_imports_card_number_idx
    ON tacho_imports (card_number) WHERE card_number IS NOT NULL;

-- Queue claim. SKIP LOCKED so several worker replicas can run without a broker
-- and without two workers taking the same file. Reusing the imports table as the
-- queue keeps the system to one moving part; a real queue only earns its place
-- when throughput justifies it.
COMMENT ON COLUMN tacho_imports.claimed_at IS
    'Set when a worker takes the row with SELECT ... FOR UPDATE SKIP LOCKED. '
    'A stale claimed_at is reclaimed by the worker after the lease expires.';

-- One row per calendar day of activity found in an import. Totals are stored
-- alongside the changes because reports must not re-derive them differently from
-- the timeline, and a stored figure can be recomputed and compared.
CREATE TABLE IF NOT EXISTS tacho_activity_days (
    id                          BIGSERIAL PRIMARY KEY,
    import_id                   BIGINT      NOT NULL
        REFERENCES tacho_imports(id) ON DELETE CASCADE,
    driver_key                  TEXT        NOT NULL,
    day                         DATE        NOT NULL,
    presence_counter            INTEGER,
    distance_km                 INTEGER,

    minutes_driving             INTEGER     NOT NULL DEFAULT 0,
    minutes_work                INTEGER     NOT NULL DEFAULT 0,
    minutes_availability        INTEGER     NOT NULL DEFAULT 0,
    minutes_rest                INTEGER     NOT NULL DEFAULT 0,
    uncovered_minutes           INTEGER     NOT NULL DEFAULT 0,
    open_ended                  BOOLEAN     NOT NULL DEFAULT FALSE,
    warnings                    JSONB       NOT NULL DEFAULT '[]'::jsonb,

    -- Two imports of the same card legitimately cover the same day. The unique
    -- key is per-import, so no import steals another's rows.
    UNIQUE (import_id, day)
);

CREATE INDEX IF NOT EXISTS tacho_activity_days_day_idx
    ON tacho_activity_days (day DESC);
CREATE INDEX IF NOT EXISTS tacho_activity_days_driver_day_idx
    ON tacho_activity_days (driver_key, day DESC);

-- Every activity change, as recorded. This is the evidence table: it is what the
-- timeline draws and what a re-calculation reads. Never overwritten in place —
-- a re-parse creates a new import.
CREATE TABLE IF NOT EXISTS tacho_activity_changes (
    id                  BIGSERIAL PRIMARY KEY,
    import_id           BIGINT      NOT NULL
        REFERENCES tacho_imports(id) ON DELETE CASCADE,
    day_id              BIGINT      NOT NULL
        REFERENCES tacho_activity_days(id) ON DELETE CASCADE,
    day                 DATE        NOT NULL,
    minute_of_day       SMALLINT    NOT NULL CHECK (minute_of_day BETWEEN 0 AND 1439),
    -- 0 rest, 1 availability, 2 other work, 3 driving (the on-file codes).
    activity            SMALLINT    NOT NULL CHECK (activity BETWEEN 0 AND 3),
    slot                SMALLINT    NOT NULL DEFAULT 0 CHECK (slot IN (0, 1)),
    crew                BOOLEAN     NOT NULL DEFAULT FALSE,
    card_not_inserted   BOOLEAN     NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS tacho_activity_changes_day_id_idx
    ON tacho_activity_changes (day_id, minute_of_day);
CREATE INDEX IF NOT EXISTS tacho_activity_changes_import_idx
    ON tacho_activity_changes (import_id);
