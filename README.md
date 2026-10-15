# GPS_Tracer

Self-hosted GPS fleet tracking and tachograph compliance for a private Italian cargo
company.

Traccar does the tracking. PostgreSQL stores it. Docker Compose runs it. Dokploy
deploys it. There is no custom tracking backend, because there should not be.

On top of that sits a **tachograph service**: it imports driver-card downloads,
normalises their activity, and reports EU driving-time findings — with the rules
version, source data and assumptions attached to every result, because a
compliance figure you cannot explain later is worse than no figure at all.

```text
TRUCK  ──▶  SinoTrack ST-906L  ──▶  4G / SIM  ──▶  TCP 5013 (H02)
                                                        │
                                          Company server  │
                                                        ▼
                                            Dokploy ──▶ Traccar
                                                        │
                                                        ▼
                                                  PostgreSQL
                                                        │
                                                        ▼
                                                  Fleet dashboard
```

---

## Quick start

```bash
git clone https://github.com/Orazen/GPS_Tracer.git
cd GPS_Tracer
./scripts/setup.sh
```

**That is the whole setup.** The one command generates both secrets, brings the
stack up, creates the first administrator — Traccar ships with **no users at
all**, so without this the stack passes every healthcheck and nobody can log in —
closes registration again behind them, runs the smoke test, and prints the URL to
open. It is safe to re-run: the second run finds the administrator and changes
nothing.

It also checks every published port **before** starting anything and names the
container that holds one, because a second copy of this stack on the same machine
is the most common way this fails. To run a second copy deliberately:

```bash
./scripts/setup.sh --env-file .env.shop2 -p gpstracer-shop2
```

`--check` runs that preflight alone and changes nothing.

The manual equivalent is [First run](#first-run) below, for a server where you
cannot run a script.

| Where | URL | What it is |
|---|---|---|
| **Dashboard** | `http://localhost:8083` | what a person actually uses: fleet map, route history, zones, reports, tachograph |
| Traccar's own UI | `http://localhost:8082` | break-glass administration, loopback only |
| Tachograph API | `http://localhost:8084` | loopback only; the dashboard proxies it and holds the service token |

`docker compose up -d` deploys under the compose project name `gpstracer-fleet`,
and that name prefixes every volume and every container. Two copies of this
project on one machine must use different project names
(`docker compose -p gpstracer-dev up -d`), or they will share one database. The
name is deliberately not the bare product name: a generic one collides with any
other stack that calls itself the same thing, and Docker gives the loser whatever
volume happens to have that name. See
[`docs/UNIMPLEMENTED.md`](docs/UNIMPLEMENTED.md) §7.

That separation only works while no service sets a fixed `container_name`, which
is why none of them does — a fixed name is not prefixed by the project, and the
second copy then cannot start at all rather than sharing a volume. Two copies
running side by side on different ports, each with its own volumes, is verified;
CI fails if a `container_name` is ever added back.

---

## A fleet to look at, without hardware

An empty database gives you an empty map, which tells you nothing about whether
the thing works. This seeds a demonstration fleet **through the real H02 protocol
on the real listener**, so Traccar's own decoder produces the positions — not a
shortcut around it:

```bash
docker compose --profile tools run --rm simulator --reset
```

It drives six trucks around a route in Milan for three hours of simulated time,
with genuine stops at each customer site, and exits when it is done. `--reset`
clears each vehicle's stored positions first, so a second run replaces the demo
data instead of piling a second trail on top of it. `--help` lists the rest
(`--city rome`, `--vehicles 4`, `--window`, `--live`).

**What it proves:** the protocol listener, Traccar's H02 decoding, position
storage, and every screen downstream of a stored position.
**What it does not:** the radio link, the SIM and APN, GNSS reception, the
device's own firmware, or ACC wiring. It is not a substitute for the physical
test in [`docs/TESTING.md`](docs/TESTING.md), and
[`docs/UNIMPLEMENTED.md`](docs/UNIMPLEMENTED.md) §1 still says so.

---

## First run

`./scripts/setup.sh` does all of this. It is documented here because the failure
it works around is the one worth understanding, and because on a server where you
cannot run a script you have to do it by hand.

Traccar creates **no** user accounts on a fresh install. There is no default
`admin/admin` in 6.16. With registration closed — the correct production
setting — there is therefore no way to create the first account, and you get a
stack that passes every healthcheck and is completely unusable.

This is a deliberate three-step bootstrap:

1. In `.env`, set `TRACCAR_ALLOW_REGISTRATION=true`
2. `docker compose up -d`, then:

   ```bash
   ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='a-strong-one' ./scripts/create-admin.sh
   ```

3. Set `TRACCAR_ALLOW_REGISTRATION=false` and `docker compose up -d` again

On Dokploy there is no `.env` file — set the variables in the Dokploy UI and run
the same script over SSH, or create the user from the dashboard while
registration is briefly enabled.

Never leave registration enabled on a reachable dashboard: anyone who finds the
URL can create an account.

---

## What this does

Reconfigured Traccar out of the box. No functionality is rebuilt.

| Need | Provided by |
|---|---|
| Live map, all vehicles, online/offline, moving/stopped | **dashboard** — Fleet |
| Speed, ignition, last update | **dashboard** — vehicle panel |
| Trip history, distance, avg/max speed, duration | **dashboard** — History and Reports |
| Route playback, with stops and arrivals | **dashboard** — History |
| Stops with duration | **dashboard** — Reports ▸ Stops |
| Geofences: depot, customer, restricted | **dashboard** — Zones, drawn and edited on the map |
| Alerts: overspeed, geofence, offline, ignition, SOS | **dashboard** — alert feed |
| **Connecting a new tracker, without a shell** | **dashboard** — Connect a tracker: the six hops with live state, the identifiers the server has already refused, and the exact SMS to send |
| Users and roles (admin / manager) | Traccar |
| Excel export | **dashboard** — Reports ▸ Export Excel, a real spreadsheet |
| Italian / English | **dashboard** — language switch |

Traccar does the work underneath all of that; the dashboard is the interface in
front of it. It serves the app and proxies Traccar and the tachograph service
from one origin, so there is one sign-in rather than three, and the tachograph
service token never reaches the browser.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for what is deliberately *not*
customised, and why.

---

### Tachograph and driving time

This is the part that is **not** Traccar configuration - it is new code, in
[`tacho/`](tacho/), running as its own two containers. It answers a different
question from the tracking stack: *whose hours are these, and are they legal?*

| Need | Provided by |
|---|---|
| Secure `.DDD` upload, hash, dedupe, import history | `tacho-api` |
| Driver-card parsing, normalised activity | `tacho-worker` (driver cards only) |
| Activity timeline, daily and weekly summaries | dashboard ▸ Tachograph ▸ Activity |
| File coverage and missing-data warnings | dashboard ▸ Tachograph ▸ Activity, from `/api/coverage` |
| Import history, status and raw evidence | dashboard ▸ Tachograph ▸ Imports |
| Who drives which vehicle, and who drove it last month | dashboard ▸ Tachograph ▸ Drivers, backed by `tacho_vehicle_assignments` |
| Driver names on the fleet screens | off by default; Tachograph ▸ Drivers records the assignment either way — see [`DASHBOARD-SPEC.md`](../DASHBOARD-SPEC.md) |
| Findings, breaches and disclosed assumptions | dashboard ▸ Tachograph ▸ Findings |
| Exportable reports with source and timestamp metadata | CSV export with a provenance header, linked from the Activity screen |
| EU driving-time findings, versioned and traceable | `tacho/rules/driving_time.py` |
| Restricted access and audit logging of driver data | role gating + `tacho_audit_log` |

> **Two things are deliberately incomplete, and must not be described otherwise:**
>
> - **No calculation has been validated against a trusted tachograph analysis
>   report.** Every stored result carries `validated_against_reference = false` and a
>   note saying so. See [`docs/DRIVING-TIME.md`](docs/DRIVING-TIME.md).
> - **The parser has only been tested against synthetic fixtures** generated by this
>   repository, never a real driver card. Vehicle-unit downloads are detected and
>   **refused**, not parsed. See [`docs/TACHO-SERVICE.md`](docs/TACHO-SERVICE.md).

Every stage has a status in [`docs/UNIMPLEMENTED.md`](docs/UNIMPLEMENTED.md) - the
single place that answers "does the system do X?" honestly.

---

## Ports

Exactly three are published, and one of them is on loopback:

| Port | Purpose | Exposure |
|---|---|---|
| `8083` | Dashboard - the app a person uses | Loopback only - put HTTPS in front |
| `8082` | Traccar's own UI, break-glass | Loopback only |
| `5013` | H02 tracker protocol | Public - the tracker must reach it |
| `8084` | Tachograph API | **Loopback only** - it serves driver personal data |

`H02_PORT` is the port on the **server**, which is what goes into the tracker's
SMS provisioning. Inside the container Traccar always listens on 5013, where it
opens h02 by default, and the host port is mapped onto it:

```yaml
- "${H02_PORT:-5013}:5013"
```

Do not "simplify" that to `${H02_PORT}:${H02_PORT}`. Traccar does not read
`H02_PORT`, so pointing the host at any other number lands the published port on
whatever protocol Traccar does listen on there — 5093, for instance, is its
*watch* listener. The stack comes up healthy, accepts the tracker's connection,
and decodes nothing. The failure is silent, and it has already happened once.

Traccar listens on ~250 protocol ports internally. The tachograph worker has no
published port at all. **None** of the rest are published. Add one only when a
tracker you actually own needs one.

PostgreSQL is never published. It is reachable only over the internal Docker
network, by Traccar and by the two tachograph containers.

---

## Documentation

| Document | Covers |
|---|---|
| [`docs/connect-hardware.html`](docs/connect-hardware.html) | **The whole path on one page** — printable bench sheet: the six hops from tracker to dashboard, and the failure each one produces |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Stack, layout, what is and is not customised |
| [`docs/DOKPLOY.md`](docs/DOKPLOY.md) | Deploy, domain, HTTPS, firewall, backups |
| [`docs/TRACKER-SETUP.md`](docs/TRACKER-SETUP.md) | Wiring, ACC, SIM, per-tracker provisioning |
| [`docs/ST-906L.md`](docs/ST-906L.md) | SinoTrack ST-906L specifics and unknowns |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Hardening, secrets, retention, upgrades |
| [`docs/TESTING.md`](docs/TESTING.md) | Bench and road acceptance tests |
| [`docs/TACHO-SERVICE.md`](docs/TACHO-SERVICE.md) | Tachograph import: architecture, API, operations, parser limits |
| [`docs/DRIVING-TIME.md`](docs/DRIVING-TIME.md) | EU rules implemented, assumptions, verification status |
| [`docs/LIVE-TACHO.md`](docs/LIVE-TACHO.md) | Live/remote tachograph integration: go/no-go, vendors, costs |
| [`docs/LICENCES.md`](docs/LICENCES.md) | Dependency licence audit, and why an AGPL parser was rejected |
| [`docs/FLEET-ACCOUNTABILITY.md`](docs/FLEET-ACCOUNTABILITY.md) | Driver identity: what of "who was driving" this system does, and what it deliberately does not |
| [`docs/UNIMPLEMENTED.md`](docs/UNIMPLEMENTED.md) | **Register of everything not done, and why** |

---

## Operations

```bash
./scripts/setup.sh               # the whole setup: secrets, stack, first admin, smoke test
./scripts/setup.sh --check       # preflight only: ports, docker, nothing changed
./scripts/create-admin.sh        # first-run administrator, by hand
./scripts/backup.sh              # database dump + uploaded tacho files + retention
./scripts/backup.sh list         # what is backed up
./scripts/backup.sh restore FILE # restore both (stops Traccar, then restarts it)
./scripts/smoke-test.sh          # is this deployment actually usable?

docker compose --profile tools run --rm simulator --reset            # demo fleet, no hardware
docker compose run --rm tacho-worker python -m tacho.worker --once   # drain the queue

./scripts/connect-tracker.py --check                                 # is the H02 port really reaching Traccar?
./scripts/connect-tracker.py --imei <imei> --name <plate> \          # register the device, print its SMS
    --server <public-ip> --apn <carrier-apn>                         # provisioning, then watch it connect
```

**Bringing a tracker online is one command.** `connect-tracker.py` checks the
published port *and* the container side of the mapping, reads back what the server
will do with an unknown identifier, creates the device record, prints the exact
SMS sequence with your APN and server substituted, and then waits — reporting
*registered*, *reached the server* or *positioned*, which are three different
things and only the last one means it works. When nothing arrives it reads
Traccar's log and names the fault, including the one with a one-command fix. It
needs Python and nothing else.

**Before wiring anything into a vehicle**, open
[`docs/connect-hardware.html`](docs/connect-hardware.html) — the whole path from
SIM to dashboard on one printable page: six numbered hops, what each one fails
silently on, and the one command that checks it.

Or open **Connect a tracker** in the dashboard, which is that sheet with live
state: the same six hops for the identifier in front of you, the settings this
server is actually running with, every identifier Traccar has already refused
(with one-click registration), and the SMS block generated from your APN and
server. Administrators only, because it reports the server's own configuration and
the raw identifiers of everything that has probed the public H02 port.

Both scripts read `.env` if present but **real environment variables win**, so
they work unchanged under Dokploy where there is no `.env`. If the stack was
brought up with a non-default project name, pass the same one to the scripts:
`COMPOSE_PROJECT_NAME=gpstracer-dev ./scripts/smoke-test.sh`.

**Backups cover both stores.** Each run writes a PostgreSQL dump *and* an archive
of the `tacho-data` volume, under one timestamp, and a restore puts both back.
That pairing is the point: an import row references a stored file, so restoring
the database alone leaves the tachograph screen referring to evidence that is no
longer there. `./scripts/backup.sh list` shows the pairs.

---

## Branding

Traccar's UI is used as-is for now. Placeholder assets live in `branding/` and
are mounted over `/opt/traccar/web/override`, so branding can be applied without
forking Traccar — see [`branding/README.md`](branding/README.md).

The client's actual identity has not been invented. Replace the placeholders
when the real name and logo arrive.

---

## Status

Reported as **passed**, **failed** or **not yet run** — never as "done" when it has
not been measured.

| Area | Status |
|---|---|
| Traccar + PostgreSQL stack | ✅ running and healthy; `/api/server` → 200 |
| **One-command setup and first admin (`scripts/setup.sh`)** | ✅ **verified end to end from a clean checkout** — generated both secrets, brought all six services up healthy, created the first administrator, closed registration again, and finished on `RESULT: all checks passed` from the smoke test. Also verified as a *second copy beside a running stack*: its own ports, its own volumes, both stacks healthy at once |
| **Two copies of this stack on one host** | ✅ **fixed and verified** — no service sets a `container_name`, because a fixed name is not prefixed by the project and the second copy could not start at all. Two copies were run side by side to prove it; CI fails if one is added back |
| Compose, healthchecks, startup ordering, ports | ✅ verified locally |
| Tachograph service (import, dedupe, normalise, report) | ✅ **353 tests pass** (exit status checked), including 61 against a real PostgreSQL and a full round trip through the containers |
| EU driving-time engine | ✅ unit-tested against hand-computed scenarios |
| Driving-time **validation against a reference report** | ❌ **NOT RUN** — no reference available. `validated_against_reference` is `false` everywhere |
| Parser against a **real driver card** | ❌ **NOT RUN** — only synthetic fixtures exist |
| Vehicle-unit / GEN2 parsing | ❌ **not implemented** — refused by design |
| **Physical GPS tracker end-to-end on H02:5013** | ❌ **NOT RUN** — no device has ever connected. The listener and decoder are exercised by `scripts/simulate-fleet.py`, and the published port was re-tested from outside the network, but the radio link, SIM and GNSS are untested |
| **Connecting a tracker to the server** | ✅ **tool-backed and verified server-side** — `./scripts/connect-tracker.py` checks the port mapping, creates the device, prints the SMS provisioning and reports *registered* / *reached the server* / *positioned*, naming the actual fault from Traccar's log when nothing arrives. The zero-touch path was verified over real H02 on the published port: an unknown identifier was created as category `truck`, and one outside the allow-list was refused and logged. What remains unverified is a physical unit sending those bytes |
| **Connect-a-tracker screen** | ✅ **built and verified in a browser** — the six hops with live state; the registration state read back from what the Traccar container rendered rather than from the documented default; the identifiers it refused, taken from its log, with one-click registration; and the SMS block asserted against the same commands the Python tests and `docs/TRACKER-SETUP.md` assert. `dashboard/scripts/verify.mjs` drives it (**61 checks, exit 0**). It cannot see the published host port and says so on the screen instead of implying a green light means the outside path works |
| **Fleet dashboard (Phase 2 UI)** | ✅ **built and verified in a browser** — Fleet, History, Zones, Reports, Tachograph and Settings, in Italian and English. `dashboard/scripts/verify.mjs` drives all of them against a seeded fleet and fails on an empty report, a corrupt export or a console error |
| Excel export | ✅ **verified as a real spreadsheet** — the download is checked for ZIP magic, not just for its file name |
| Fleet simulator (H02, no hardware) | ✅ **works** — 1056 fixes over three simulated hours, every packet acknowledged by Traccar's own H02 decoder |
| Backup covering the tachograph volume | ✅ **automated** — one run writes the database dump and the uploaded-file archive together; the archive was restored into a scratch volume and matched the live one |
| Smoke test covering the tachograph service | ✅ **extended** — health, refusal without the service token, acceptance with it, and role gating on the access log |
| Live/remote tachograph integration | ❌ **not implemented** — investigated in [`docs/LIVE-TACHO.md`](docs/LIVE-TACHO.md) |
| Dokploy deployment | 📄 **documented, unverified** |
| Automated tests in CI | ✅ **configured** — [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the Python suite twice (without a database, then with PostgreSQL), runs the provisioning tool's own 79 tests, builds the dashboard, asserts the compose port mappings and that the auto-registration settings render into valid XML, and now also fails on a reintroduced `container_name`, on a shell script that does not parse, and unless `setup.sh --check` passes |

The short version: **the tracking infrastructure, the dashboard and the tachograph
service are built and tested; the hardware and the external validation are not.**

Order one tracker, work through [`docs/TESTING.md`](docs/TESTING.md), and only
then buy more. Before any compliance claim, work through
[`docs/DRIVING-TIME.md`](docs/DRIVING-TIME.md) §7.
