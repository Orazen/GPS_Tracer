# Architecture

## What this system is

A configured [Traccar](https://www.traccar.org/) deployment. Traccar is the
tracking engine; this repository supplies the container stack, the database, the
configuration, and the operational documentation.

## What is deliberately NOT built

This is the most important section of this document.

Traccar already does all of the following, correctly and with years of field
testing behind it. Rebuilding any of it would be strictly worse:

- GPS protocol decoding (H02, GT06, and ~200 others)
- Trip detection and reconstruction
- Position storage and retention
- The geofencing engine and geofence enter/exit events
- Event generation (moving, stopped, alarm, geofence, SOS)
- The reporting engine (trips, stops, summary, route, events)
- The web dashboard, map, and calendar UI
- User, device, group, and permission management
- WebSocket live updates

**None of that is reimplemented here.** There is no custom backend, no custom
map component, and no custom dashboard in this repository.

If a requirement cannot be met by Traccar configuration, that is the moment to
justify custom code — not before.

---

## Stack

| Component | Choice | Why |
|---|---|---|
| Tracking engine | Traccar 6.16 (pinned) | Protocol coverage, mature, GPL-2.0 |
| Database | PostgreSQL 16 | Specified; robust, well-known backup tooling |
| Orchestration | Docker Compose | Simple, portable, Dokploy-native |
| Deployment | Dokploy | Git-based deploys with TLS and backups |
| Dashboard | Traccar's own UI | No rebuild needed |
| Map | Traccar's default (OSM-based) | Free, no API key |

### Version pinning

`traccar/traccar:6.16-alpine` is pinned, never `:latest`. An unpinned tag means
an upgrade happens silently on the next restart — and Traccar runs irreversible
Liquibase schema migrations on boot. Pin it, and upgrade deliberately after a
backup. See [`SECURITY.md`](SECURITY.md#upgrades).

### Why PostgreSQL and not the embedded H2

H2 is Traccar's default and is fine for evaluation. For a fleet that a business
depends on: it is a single file with a single writer, its backup story is poor,
and it is not what any competent DBA expects to restore. PostgreSQL gives
`pg_dump`, point-in-time recovery, and a database you can hand to someone else.

Traccar auto-creates its schema on first boot, so there is no migration step to
manage.

---

## Configuration: why there is a shell script

Traccar 6.16 has **no environment-variable configuration**. There is no
`TRACCAR_*` handling in `tracker-server.jar` — verified by scanning the jar's
string table. It reads `conf/traccar.xml` and nothing else.

So to keep the database password out of Git while still using a real config file,
`traccar/config/entrypoint.sh` renders `traccar.xml` from environment variables at
container start. The rendered file lands in a Docker named volume, never in the
repository, and is gitignored in case that changes.

### Two formatting traps that cause crash-loops

Both were hit while building this and both fail unhelpfully — the container just
restarts:

1. **DOCTYPE.** Java's `java.util.Properties` XML parser only accepts its own:

   ```xml
   <!DOCTYPE properties SYSTEM 'http://java.sun.com/dtd/properties.dtd'>
   ```

   Traccar's own `traccar.dtd` (which uses `<traccar><property>` elements) is
   rejected with the misleading *"must contain the DOCTYPE declaration"*.

2. **Single-line values.** The Properties parser silently truncates any value
   containing a newline.

`entrypoint.sh` validates both before exec'ing the JVM, and refuses to start if
`POSTGRES_PASSWORD` is still `CHANGE_ME`.

---

## Repository layout

```text
GPS_Tracer/
├── README.md
├── docker-compose.yml          the whole stack
├── .env.example                every variable, documented
├── .gitignore
│
├── traccar/
│   └── config/
│       └── entrypoint.sh       renders traccar.xml from env vars
│
├── branding/
│   ├── README.md
│   ├── assets/                 placeholders only
│   └── override/               mounted at /opt/traccar/web/override
│
├── docs/
│   ├── ARCHITECTURE.md         this file
│   ├── DOKPLOY.md              deploy, TLS, firewall, backups
│   ├── TRACKER-SETUP.md        wiring, SIM, provisioning
│   ├── ST-906L.md              device specifics and open questions
│   ├── SECURITY.md             hardening, secrets, retention, upgrades
│   └── TESTING.md              bench + road acceptance tests
│
└── scripts/
    ├── create-admin.sh         first-run administrator
    └── backup.sh               pg_dump / pg_restore with retention
```

---

## Data flow

**Positions in.** The tracker opens a TCP connection to port 5013 and speaks H02.
Traccar decodes it, resolves the device by its identifier, geofences the position
against the device's zones, writes the row to PostgreSQL, and emits any resulting
events.

**Positions out.** The dashboard subscribes over WebSocket
(`/api/session?token=...`) and receives position updates live. Report screens use
the REST API.

**Positions out (tachograph).** Driver-card downloads are uploaded to `tacho-api`,
queued in `tacho_imports`, parsed by `tacho-worker`, and normalised into
`tacho_activity_days` / `tacho_activity_changes`. The tachograph service never writes
to a `tc_` table, and Traccar never reads a `tacho_` table.

There is no cache and no cron. The one background process is `tacho-worker`, which
polls its own table.

---

## Data model

Traccar creates its own schema on first boot. The tables that matter:

| Table | Holds |
|---|---|
| `tc_devices` | Trackers |
| `tc_positions` | Every fix — the largest table by far |
| `tc_events` | Alarms, geofence transitions, state changes |
| `tc_geofences` | Zones, as WKT (`CIRCLE (lat lon, radius_m)`) |
| `tc_users` | Accounts |
| `tc_device_geofence` | Which zones apply to which device |
| `tc_server_attributes` | Per-device computed settings |

`tc_positions` is where the storage cost lives: a truck reporting every 30
seconds generates ~2,900 rows/day, ~1M rows/year. Retention is therefore
configurable — see [`SECURITY.md`](SECURITY.md#data-retention).

---

## The tachograph service

Everything above is Traccar configuration. The tachograph service is the one part of
this repository that is **new code**, because Traccar cannot answer the question it
answers: Traccar knows where a vehicle went, not who was driving it or how many hours
they are owed.

| Component | Choice | Why |
|---|---|---|
| Language | Python 3.12 | The parser and the rules engine are pure standard library — no third-party licence or upgrade reaches the code that decides somebody's hours |
| HTTP | FastAPI | Small surface, typed request models, and a dependency system that keeps role gating in one place |
| Database | The same PostgreSQL | Tables in the `tacho_` namespace, so there is no second database to back up, size, monitor or secure |
| Queue | `tacho_imports` + `FOR UPDATE SKIP LOCKED` | A broker would be a second moving part at a throughput that does not need one |
| Process split | `tacho-api` + `tacho-worker`, one image | The spec requires parsing out of the web request; two processes is the honest way to do it |
| Storage | Content-addressed private volume | Originals preserved and hashed, **no URL that returns them** |
| Migrations | Ordered immutable `.sql` + checksum ledger | Editing an applied migration stops the service instead of silently skipping |

### Why the parser is in this repository

See [`LICENCES.md`](LICENCES.md) §5. In short: every established `.DDD` parser is
either copyleft (ReadESM, GPL; `tachoparser`, AGPL-3.0) or a Go/Ruby/C# package that
cannot be imported here. Rather than inherit an obligation or guess at offsets, the
GEN1 driver-card format was implemented from the regulation, in this repository, with
the parts that could not be verified explicitly refused rather than guessed.

### The one architectural rule worth stating

**A gap in the records is `unknown`; it is never `rest`.** Every layer is built
around that: the parser refuses to bridge a gap in the cyclic activity buffer, the
rules engine refuses to bridge a gap between records, and the API's coverage endpoint
tells the caller which days are missing before it shows any rest finding. An engine
that silently fills a gap produces a confidently wrong compliance number, which is
the worst possible failure for this kind of software.

See [`TACHO-SERVICE.md`](TACHO-SERVICE.md), [`DRIVING-TIME.md`](DRIVING-TIME.md) and
[`UNIMPLEMENTED.md`](UNIMPLEMENTED.md).

---

## Multi-tenancy

One Traccar user per customer is the tenancy boundary: Traccar's API only ever
returns devices the authenticated user is permitted to see, so users do not see
each other's trucks without any extra code.

For now there is one company and two roles (Owner, Fleet Manager). Nothing here
prevents additional isolated customers later, but nothing here should be built
for multi-tenancy until a second customer actually exists.

---

## Known constraints

Stated plainly so they are not rediscovered painfully:

- **Traccar creates no users on first boot.** See the First run section of the
  README. Hand-rolling a password hash to seed one is a trap: Traccar uses
  `PBKDF2WithHmacSHA256` at 200,000 iterations and storing only the salt, so a
  hash generated by a different implementation simply fails to log in. The
  supported bootstrap flag is used instead.
- **`GET /api/session` returns 404, not 401,** when there is no session. Any
  custom client must treat 404 as "not authenticated" on that endpoint.
- **Login takes `email`, not `username`,** and the response body carries no
  token — authentication is the `JSESSIONID` cookie alone.
- **Report endpoints return XLSX by default.** `?format=json` is ignored; only an
  `Accept: application/json` header switches them. This bites every custom
  integration.
- **A Compose project name change silently orphans named volumes.** The project
  name is the volume prefix, so renaming it gives you a fresh, empty database and
  leaves the real one behind. Do not rename `gpstracer`.
