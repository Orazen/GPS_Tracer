-- Sales, orders, deliveries and traceability.

CREATE TABLE IF NOT EXISTS scrap_customers (
    id            SERIAL PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    email         TEXT,
    phone         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scrap_orders (
    id            SERIAL PRIMARY KEY,
    order_number  TEXT NOT NULL UNIQUE,
    customer_code TEXT REFERENCES scrap_customers(code),
    load_id       TEXT REFERENCES scrap_loads(load_id),
    status        TEXT NOT NULL DEFAULT 'draft',
    total_amount  DOUBLE PRECISION NOT NULL DEFAULT 0,
    currency      TEXT NOT NULL DEFAULT 'EUR',
    created_by    TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scrap_order_items (
    id            SERIAL PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES scrap_orders(id) ON DELETE CASCADE,
    material_code TEXT NOT NULL REFERENCES scrap_materials(code),
    quantity      DOUBLE PRECISION NOT NULL,
    unit          TEXT NOT NULL DEFAULT 'kg',
    price_per_unit DOUBLE PRECISION NOT NULL DEFAULT 0,
    line_total    DOUBLE PRECISION NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS scrap_deliveries (
    id            SERIAL PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES scrap_orders(id) ON DELETE CASCADE,
    load_id       TEXT REFERENCES scrap_loads(load_id),
    status        TEXT NOT NULL DEFAULT 'pending',
    delivered_at  TIMESTAMPTZ,
    delivered_by  TEXT,
    notes         TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_scrap_orders_status ON scrap_orders(status);
CREATE INDEX IF NOT EXISTS idx_scrap_orders_customer ON scrap_orders(customer_code);
CREATE INDEX IF NOT EXISTS idx_scrap_deliveries_order ON scrap_deliveries(order_id);
