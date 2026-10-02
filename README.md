# GPS_Tracer

Self-hosted GPS fleet tracking for a private Italian cargo company.

Traccar does the tracking. PostgreSQL stores it. Docker Compose runs it. Dokploy
deploys it. There is no custom tracking backend, because there should not be.

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

cp .env.example .env
$EDITOR .env          # set POSTGRES_PASSWORD at minimum

docker compose up -d
```

Then create the first administrator — see [First run](#first-run), because
Traccar ships with **no users at all** and the stack will look healthy while
nobody can log in.

Dashboard: `http://localhost:8082`

---

## First run

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
| Live map, all vehicles, online/offline, moving/stopped | Traccar UI |
| Speed, ignition, last update | Traccar UI |
| Trip history, distance, avg/max speed, duration | Traccar reports |
| Route playback | Traccar UI |
| Stops with duration and address | Traccar reports |
| Geofences: depot, customer, restricted | Traccar UI + events |
| Alerts: overspeed, geofence, offline, ignition, SOS | Traccar notifications |
| Users and roles (admin / manager) | Traccar |
| Excel export | Traccar reports |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for what is deliberately *not*
customised, and why.

---

## Ports

Exactly two are published:

| Port | Purpose | Exposure |
|---|---|---|
| `8082` | Dashboard | Loopback only — put HTTPS in front |
| `5013` | H02 tracker protocol | Public — the tracker must reach it |

Traccar listens on ~250 protocol ports internally. **None** of them are
published. Add one only when a tracker you actually own needs it.

PostgreSQL is never published. It is reachable only by Traccar over the internal
Docker network.

---

## Documentation

| Document | Covers |
|---|---|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Stack, layout, what is and is not customised |
| [`docs/DOKPLOY.md`](docs/DOKPLOY.md) | Deploy, domain, HTTPS, firewall, backups |
| [`docs/TRACKER-SETUP.md`](docs/TRACKER-SETUP.md) | Wiring, ACC, SIM, per-tracker provisioning |
| [`docs/ST-906L.md`](docs/ST-906L.md) | SinoTrack ST-906L specifics and unknowns |
| [`docs/SECURITY.md`](docs/SECURITY.md) | Hardening, secrets, retention, upgrades |
| [`docs/TESTING.md`](docs/TESTING.md) | Bench and road acceptance tests |

---

## Operations

```bash
./scripts/create-admin.sh        # first-run administrator
./scripts/backup.sh              # PostgreSQL dump + retention
./scripts/backup.sh list         # what is backed up
./scripts/backup.sh restore FILE # restore (stops Traccar, then restarts it)
```

Both scripts read `.env` if present but **real environment variables win**, so
they work unchanged under Dokploy where there is no `.env`.

---

## Branding

Traccar's UI is used as-is for now. Placeholder assets live in `branding/` and
are mounted over `/opt/traccar/web/override`, so branding can be applied without
forking Traccar — see [`branding/README.md`](branding/README.md).

The client's actual identity has not been invented. Replace the placeholders
when the real name and logo arrive.

---

## Status

Infrastructure and deployment are working and tested. **No physical tracker has
been tested yet** — the H02 integration is documented but unverified, and
`docs/ST-906L.md` lists exactly what is assumed versus confirmed.

Order one tracker, work through [`docs/TESTING.md`](docs/TESTING.md), and only
then buy more.
