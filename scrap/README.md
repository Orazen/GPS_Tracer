# Scrap service (GPS_Tracer)

Scrap-metal fleet and inventory management: loads, QR codes, weigh tickets, stock ledger, audit.

- Runs on port 8085, loopback only.
- Tables in `scrap_*` namespace of the shared PostgreSQL.
- Auth: service token + forwarded actor/role, mirroring tacho.
- Negative stock prevented by default.

## Endpoints

- POST/GET /api/materials
- POST/GET /api/warehouses
- POST/GET /api/loads, GET /api/loads/{id}, POST /api/loads/{id}/status
- POST /api/weigh, GET /api/loads/{id}/weigh-tickets
- POST /api/stock/movements, GET /api/stock/balance, GET /api/stock/movements
- GET /api/audit, GET /api/meta, GET /healthz

## Tests

```bash
cd scrap
pip install -r requirements-dev.txt
pytest                      # pure logic + skipped DB tests
SCRAP_TEST_DATABASE_URL=... pytest tests/test_service_db.py
```