# Repository audit (GPS_Tracer)

Date: 28 Oct 2026. Branch: main (synced to origin/main 7d4e9da).

## Existing stack

- Traccar 6.16 (pinned, Alpine) as GPS engine.
- PostgreSQL 16 (named volume) shared by Traccar and services.
- Docker Compose (project name gpstracer-fleet).
- Dashboard: React 18 + Vite, served on 8083, proxies Traccar (8082) and tachograph (8084).
- Tachograph service: Python FastAPI, tables tacho_*, port 8084.
- Scrap service (new): Python FastAPI, tables scrap_*, port 8085.

## Existing capabilities

- Live map, positions, trips, geofences, reports, alerts via Traccar.
- Device/tracker provisioning tooling (connect-tracker.py).
- Tachograph .DDD import, activity, driving-time findings.
- Backup/restore, smoke tests, CI.

## Gaps vs. full spec

- Scrap loads/QR/weighing/stock: backend done (scrap service), UI pending.
- Sales/orders, delivery traceability: not implemented.
- Notifications (email/WhatsApp): not implemented.
- Reports for scrap: not implemented.
- Hardware (tracker) untested.

## Risks

- Postgres shared across services; migration discipline required.
- No remote configured originally; now origin set to Orazen/GPS_Tracer.
- .env secrets must never be committed.