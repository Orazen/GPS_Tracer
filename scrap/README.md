# Scrap service (GPS_Tracer)

Scrap-metal fleet and inventory management: loads, QR codes, weigh tickets, stock ledger, sales, audit.

- Runs on port 8085, loopback only.
- Tables in `scrap_*` namespace of the shared PostgreSQL. Migrations in `migrations/` are applied once each and checksummed; never edit an applied one.
- Auth: service token + forwarded actor/role, mirroring tacho.
- Negative stock prevented by default.

## Endpoints

- POST/GET /api/materials
- POST/GET /api/warehouses
- POST/GET /api/loads, GET /api/loads/{id}, POST /api/loads/{id}/status
- POST /api/weigh, GET /api/loads/{id}/weigh-tickets
- POST /api/stock/movements, GET /api/stock/balance, GET /api/stock/movements
- POST/GET /api/customers
- POST/GET /api/orders, GET /api/orders/{number}, POST /api/orders/{number}/status
- POST /api/deliveries, POST /api/deliveries/{id}/confirm
- GET /api/trace/{load_id}, GET /api/reports/loads.csv
- GET /api/audit, GET /api/meta, GET /healthz

## Authorisation

- Reads: any known role.
- Writes: `owner`, `fleet_manager`, `warehouse_operator`. `viewer` is read-only.
- Roles come only from the `X-Actor-Role` header that the dashboard server sets from the signed-in user. Unknown or missing roles are treated as `viewer` (fail closed). A request is only trusted if it also presents the service token (`Authorization: Bearer` or `X-Service-Token`), so a browser cannot choose its own role; the browser never holds the token.
- `X-Forwarded-For` is trusted for the audit `source_ip`. That value is only as good as the proxy in front of the service and should not be used for access decisions.

## Idempotency

Mutating creates accept an optional `Idempotency-Key` header (8–128 chars of letters, digits, `.`, `_`, `:`, `-`). Supported on: `POST /api/loads`, `/api/weigh`, `/api/stock/movements`, `/api/orders`, `/api/deliveries`.

- A retry with the same key and the same body returns the original result with status **200** and header `Idempotent-Replayed: true`. Nothing is written twice and no second audit row is made.
- The same key with a different body returns **409**.
- Keys are scoped by route and actor, so two users may reuse the same string.
- Without a key the request is not deduplicated (each call creates a new record).

## Business rules

- **Loads**: no implicit duplicate detection. Use an `Idempotency-Key` to make retries safe. A truck with an open load is not refused.
- **Weighing**: a load has one active weigh ticket. A second weigh returns **409** unless the request sets `allow_reweigh: true` **and** a non-blank `supersede_reason`. The earlier ticket is kept, marked superseded, and listed with `active: false`. The load row is locked during the weigh, so two concurrent weighs cannot both become active.
- **Stock**: movements are append-only. There are no update or delete routes for movements. A correction is an `adjustment` movement with a signed quantity and a required `reason`. The balance check and insert run under a per-(material, warehouse) advisory lock, so concurrent issues cannot take stock negative.
- **Deliveries**: confirmation is single-shot. A second confirm returns **409** (with who and when confirmed the first time) and does not overwrite the first confirmation.
- **Trace**: `GET /api/trace/{load_id}` returns every movement and order linked to the load, with no list limit.

## Tests

```bash
cd scrap
pip install -r requirements-dev.txt
pytest                      # pure logic, JS client contract; DB tests skipped
SCRAP_TEST_DATABASE_URL=postgresql://user:pass@127.0.0.1:5432/test pytest
```

`tests/test_guards_db.py` covers idempotency, weigh and delivery guards, stock corrections, trace limits and role enforcement. `tests/test_dashboard_client_contract.py` checks that `dashboard/src/api/scrap.js` calls endpoints that exist, and sends `Idempotency-Key` only where the handler reads it. It does not run the JavaScript.
