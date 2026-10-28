-- Scrap service core schema.
-- Materials, warehouses, loads, weigh tickets, stock movements, audit log.

CREATE TABLE IF NOT EXISTS scrap_materials (
    id            SERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    category      TEXT NOT NULL,
    unit          TEXT NOT NULL DEFAULT 'kg',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scrap_warehouses (
    id            SERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    location      TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scrap_loads (
    id            SERIAL PRIMARY KEY,
    load_id       TEXT NOT NULL UNIQUE,
    truck_ref     TEXT,
    driver_ref    TEXT,
    customer_ref  TEXT,
    supplier_ref  TEXT,
    origin        TEXT,
    destination   TEXT,
    material_code TEXT REFERENCES scrap_materials(code),
    status        TEXT NOT NULL DEFAULT 'created',
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scrap_weigh_tickets (
    id            SERIAL PRIMARY KEY,
    load_id       TEXT REFERENCES scrap_loads(load_id),
    gross         DOUBLE PRECISION NOT NULL,
    tare          DOUBLE PRECISION NOT NULL,
    net           DOUBLE PRECISION NOT NULL,
    unit          TEXT NOT NULL DEFAULT 'kg',
    ticket_number TEXT,
    scale_ref     TEXT,
    operator      TEXT,
    weighed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scrap_stock_movements (
    id            SERIAL PRIMARY KEY,
    material_code TEXT NOT NULL REFERENCES scrap_materials(code),
    warehouse_code TEXT NOT NULL REFERENCES scrap_warehouses(code),
    movement_type TEXT NOT NULL,
    quantity      DOUBLE PRECISION NOT NULL,
    unit          TEXT NOT NULL DEFAULT 'kg',
    reference     TEXT,
    actor         TEXT,
    reason        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scrap_audit_log (
    id            SERIAL PRIMARY KEY,
    actor         TEXT,
    actor_role    TEXT,
    action        TEXT NOT NULL,
    subject_type  TEXT,
    subject_id    TEXT,
    detail        JSONB,
    source_ip     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scrap_loads_status ON scrap_loads(status);
CREATE INDEX IF NOT EXISTS idx_scrap_stock_movements_material ON scrap_stock_movements(material_code);
CREATE INDEX IF NOT EXISTS idx_scrap_stock_movements_warehouse ON scrap_stock_movements(warehouse_code);
