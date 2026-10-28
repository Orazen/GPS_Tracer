# Implementation plan (GPS_Tracer)

## Phase 1 — Repository audit (done)

Existing stack: Traccar 6.16 + PostgreSQL 16 + Docker Compose + dashboard (React/Vite) + tachograph service (Python). See docs/ARCHITECTURE.md and docs/UNIMPLEMENTED.md.

## Phase 2 — Research and architecture (done)

See docs/REUSE-MATRIX.md. Decision: Traccar as GPS engine; new `scrap` service for business modules.

## Phase 3 — Proposed architecture

- GPS engine: Traccar (unchanged). Position storage remains in `tc_*` tables.
- Business service: `scrap/` (Python FastAPI), tables in `scrap_*` namespace, same PostgreSQL.
- Auth: service token between dashboard and scrap API; forwarded actor/role, mirroring tachograph service.
- QR codes generated per load, stored as PNG in `scrap-data` volume.
- Dashboard proxies scrap API like tachograph (future: add screens).

## Phase 4 — Vertical slice (implemented)

- `scrap/` service with materials, warehouses, loads, QR, weigh tickets (net = gross - tare), stock movements (ledger), balance, negative-stock prevention, audit log.
- Migrations, tests (23 passing), Docker image, compose integration.

## Phase 5 — Next

- Sales/orders, delivery confirmation, traceability links.
- Notifications (email/in-app), reports, CSV export.
- Dashboard screens for scrap modules.
- Tachograph cross-check vs GPS (future).

## Phase 6 — Tests, security, docs, release

- Automated tests, security review, deployment docs, release packaging.

## Missing features ranked by priority

1. (P1) Scrap load registry + QR — done (backend).
2. (P1) Weighbridge (gross/tare/net) — done (backend).
3. (P1) Stock ledger with negative prevention — done (backend).
4. (P2) Dashboard UI for scrap modules — pending.
5. (P2) Sales/orders and delivery traceability — pending.
6. (P2) Notifications and reports — pending.
7. (P3) Tachograph remote download — blocked on hardware.
8. (P3) Multi-tenancy — only when second customer exists.