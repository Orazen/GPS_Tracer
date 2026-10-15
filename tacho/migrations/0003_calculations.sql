-- ---------------------------------------------------------------------------
-- 0003_calculations.sql — versioned driving-time calculation runs
--
-- The single most important property of this table: **a stored result can always
-- be explained.** Every row records the rules version, the code version, the exact
-- source days used, the coverage that was available and the assumptions made.
--
-- When the rules change, existing rows are NOT rewritten. A new run is inserted
-- with a new rules_version, and both remain queryable. Anyone looking at an
-- August figure can see it was produced by rules 2026.1, not by today's engine.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS tacho_calculations (
    id                  BIGSERIAL PRIMARY KEY,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- What was calculated, and from when.
    driver_key          TEXT        NOT NULL,
    period_start        DATE        NOT NULL,
    period_end          DATE        NOT NULL,
    CHECK (period_end >= period_start),

    -- Which rules produced this. Named, versioned and citable.
    rules_version       TEXT        NOT NULL,
    engine_version      TEXT        NOT NULL,

    -- The honest status. 'ok' means the inputs covered the period and the engine
    -- could answer; 'insufficient_data' and 'stale' mean it could not, and the
    -- caller must present that rather than a number.
    status              TEXT        NOT NULL
        CHECK (status IN ('ok', 'insufficient_data', 'stale', 'not_applicable')),

    -- Which calendar days of source data were actually present, and which were
    -- missing. Storing the gap is what lets the UI say "unknown" precisely rather
    -- than vaguely.
    source_days         DATE[]      NOT NULL DEFAULT '{}',
    missing_days        DATE[]      NOT NULL DEFAULT '{}',
    source_import_ids   BIGINT[]    NOT NULL DEFAULT '{}',

    -- The computed figures, in minutes, as a JSON object so the shape can grow
    -- without a migration. Keys are documented in tacho/rules/driving_time.py.
    result              JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- Every assumption the engine made, in plain language, so the output is
    -- auditable by a human who is not the author.
    assumptions         JSONB       NOT NULL DEFAULT '[]'::jsonb,
    warnings            JSONB       NOT NULL DEFAULT '[]'::jsonb,

    -- Whether the numbers were checked against anything external. Defaults to
    -- false and must be set honestly: the spec forbids advertising the
    -- calculation as legally authoritative without expert validation.
    validated_against_reference BOOLEAN NOT NULL DEFAULT FALSE,
    validation_note     TEXT
);

CREATE INDEX IF NOT EXISTS tacho_calculations_driver_idx
    ON tacho_calculations (driver_key, period_end DESC);
CREATE INDEX IF NOT EXISTS tacho_calculations_rules_idx
    ON tacho_calculations (rules_version);

COMMENT ON COLUMN tacho_calculations.validated_against_reference IS
    'True only when the figures in this row were checked against a trusted '
    'tachograph analysis report. No row in this deployment is true: no reference '
    'report has been available. See docs/DRIVING-TIME.md.';
