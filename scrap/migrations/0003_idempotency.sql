-- Idempotency keys, one-active-weigh-per-load, and traceability lookup indexes.
--
-- idempotency_key is the server-scoped key (route|actor|client key). NULL for
-- requests that did not send an Idempotency-Key; NULLs do not collide in a
-- unique index, so unkeyed requests are unaffected.
--
-- Existing data: before this migration a load could be weighed more than once.
-- Those earlier weigh tickets are marked superseded (kept for audit, not deleted)
-- so that exactly one ticket per load is active.

ALTER TABLE scrap_loads ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE scrap_loads ADD COLUMN IF NOT EXISTS request_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_scrap_loads_idempotency ON scrap_loads(idempotency_key);

ALTER TABLE scrap_weigh_tickets ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE scrap_weigh_tickets ADD COLUMN IF NOT EXISTS request_hash TEXT;
ALTER TABLE scrap_weigh_tickets ADD COLUMN IF NOT EXISTS superseded_at TIMESTAMPTZ;
ALTER TABLE scrap_weigh_tickets ADD COLUMN IF NOT EXISTS supersede_reason TEXT;

UPDATE scrap_weigh_tickets AS older
   SET superseded_at = now(),
       supersede_reason = 'migration 0003: earlier duplicate weigh'
 WHERE older.superseded_at IS NULL
   AND EXISTS (
       SELECT 1 FROM scrap_weigh_tickets newer
        WHERE newer.load_id = older.load_id
          AND newer.superseded_at IS NULL
          AND (newer.weighed_at, newer.id) > (older.weighed_at, older.id)
   );

CREATE UNIQUE INDEX IF NOT EXISTS ux_scrap_weigh_idempotency ON scrap_weigh_tickets(idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS ux_scrap_weigh_one_active ON scrap_weigh_tickets(load_id) WHERE superseded_at IS NULL;

ALTER TABLE scrap_stock_movements ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE scrap_stock_movements ADD COLUMN IF NOT EXISTS request_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_scrap_movements_idempotency ON scrap_stock_movements(idempotency_key);

ALTER TABLE scrap_orders ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE scrap_orders ADD COLUMN IF NOT EXISTS request_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_scrap_orders_idempotency ON scrap_orders(idempotency_key);

ALTER TABLE scrap_deliveries ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
ALTER TABLE scrap_deliveries ADD COLUMN IF NOT EXISTS request_hash TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS ux_scrap_deliveries_idempotency ON scrap_deliveries(idempotency_key);

CREATE INDEX IF NOT EXISTS idx_scrap_stock_movements_reference ON scrap_stock_movements(reference);
CREATE INDEX IF NOT EXISTS idx_scrap_orders_load ON scrap_orders(load_id);
