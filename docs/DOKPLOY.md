# Deploying with Dokploy

Target: a small VPS with Docker and Dokploy installed. For a 1–5 truck pilot, 2
vCPU and 2 GB RAM is ample; PostgreSQL and Traccar together sit well under 1 GB.

---

## 1. Create the project

In Dokploy:

1. **Projects → Create Project**, name it `gpstracer`.
2. **Services → Create Service → Compose**, point it at `Orazen/GPS_Tracer`.

Docker Compose prefixes named volumes with the project name, so the project name
is effectively part of your data's identity. **Do not rename it after the first
deploy** — you will get a brand new empty database and leave the real one behind.

---

## 2. Environment variables

Dokploy serves the Compose file directly from Git, so there is no `.env` file to
create. Set these under the service's **Environment** tab instead. That also
keeps every secret out of Git.

Copy the block from [`.env.example`](../.env.example) and fill in:

| Variable | Notes |
|---|---|
| `TZ` | `Europe/Rome` |
| `POSTGRES_DB` | `traccar` |
| `POSTGRES_USER` | `traccar` |
| `POSTGRES_PASSWORD` | **generate**: `openssl rand -base64 24` |
| `TRACCAR_WEB_PORT` | `8082` |
| `H02_PORT` | `5013` |
| `TRACCAR_LOG_LEVEL` | `info` |
| `JAVA_OPTS` | keep the default for a pilot |
| `POSITION_RETENTION_DAYS` | `180` — see [SECURITY.md](SECURITY.md#data-retention) |
| `ADMIN_NAME` / `ADMIN_EMAIL` / `ADMIN_PASSWORD` | used by `create-admin.sh` |
| `TRACCAR_ALLOW_REGISTRATION` | `true` **only** for the first run |

Rules that are not optional:

- No `$`, `"`, `'`, `\` or spaces in any password. The rendered `traccar.xml` is
  XML; an unescaped `&` corrupts it and the container crash-loops.
- Quote any value containing spaces (`JAVA_OPTS="-Xms256m -Xmx1024m"`).
- Use **Generate** in the Dokploy UI where it offers one — it avoids the escaping
  problem entirely.

---

## 3. Deploy

**Deploy.** Watch the logs. The first boot runs every Liquibase migration and
takes a couple of minutes; the container stays `starting` until it is done, which
is normal.

Verify:

```bash
curl -s https://YOUR_DOMAIN/api/server
```

---

## 4. Domain and HTTPS

**Settings → Domains** on the service:

- add `fleet.example.com`
- set **HTTPS** to enabled and let Dokploy issue a certificate (Let's Encrypt)

Dokploy terminates TLS and proxies to the container's `8082`. That is the only
browser-facing port. It is bound to `127.0.0.1` in the Compose file precisely so
it cannot be reached except through the proxy.

**Human dashboard traffic is HTTPS only.** Traccar itself does not terminate TLS
and should not be exposed directly.

---

## 5. Create the first administrator

Traccar ships with no users. With registration closed there is no way to make
one, so this step is required before anything else works.

1. Set `TRACCAR_ALLOW_REGISTRATION=true` in Dokploy's Environment tab
2. **Redeploy**
3. Over SSH on the server, from the repository checkout:

   ```bash
   ADMIN_EMAIL=you@example.com ADMIN_PASSWORD='...' ./scripts/create-admin.sh
   ```

4. Set `TRACCAR_ALLOW_REGISTRATION=false`
5. **Redeploy** again

Confirm registration really is closed afterwards:

```bash
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://fleet.example.com/api/users \
  -H 'Content-Type: application/json' \
  -d '{"name":"x","email":"x@y.z","password":"Abc12345"}'
# expect 400
```

Then sign in at `https://fleet.example.com` and change the password.

---

## 6. Open the tracker port

`5013` must be reachable from the public internet — it is how the tracker in the
truck reaches the server. Verify from outside your network:

```bash
# from your phone, on mobile data
nc -vz fleet.example.com 5013
```

Port 5013 speaks raw H02 over plain TCP with no TLS. That is a property of the
protocol, not a shortcut. See [`ST-906L.md`](ST-906L.md) for what that means and
whether your SIM provider can be narrowed by source IP.

Dokploy's proxy handles HTTP. For a raw TCP port, open it at the **host
firewall** level, not in the Dokploy proxy.

---

## 7. Firewall

Only three things should be reachable from the internet:

| Port | Source |
|---|---|
| `22` | your IP only, or use a VPN |
| `80` / `443` | anywhere — Dokploy's certificate and proxy |
| `5013` | anywhere — unless your SIM provider publishes egress ranges |

Everything else, including `8082` and `5432`, stays private.

```bash
# example: ufw
ufw default deny incoming
ufw allow 22/tcp
ufw allow 80,443/tcp
ufw allow 5013/tcp
ufw enable
```

Then confirm PostgreSQL really is unreachable from outside:

```bash
nmap -p 5432 fleet.example.com     # expect: filtered
```

---

## 8. Persistent volumes

The prefix is the compose project name, `gpstracer-fleet` by default. Five named
volumes hold everything:

| Volume | Holds | Losing it means |
|---|---|---|
| `gpstracer-fleet_db-data` | the entire fleet database, including the `tacho_*` tables | total data loss |
| `gpstracer-fleet_tacho-data` | uploaded driver cards | imports point at files that are gone; the database is not enough on its own |
| `gpstracer-fleet_traccar-data` | attachments, media | losing uploads only |
| `gpstracer-fleet_traccar-logs` | log files | losing history only |
| `gpstracer-fleet_traccar-conf` | the rendered `traccar.xml` | nothing — regenerated at every start |

`db-data` and `tacho-data` must be backed up **together**: an import row
references a stored file, and restoring one without the other leaves the
tachograph screen referring to evidence that is no longer there.

Verify they exist and are not anonymous:

```bash
docker volume ls | grep gpstracer-fleet
```

`gpstracer-fleet_traccar-conf` holds the rendered `traccar.xml` with your database
password in it. It is regenerated on every start, so it does not need backing up
— but it does mean anyone with Docker access can read the password. That is the
same trust boundary as the Dokploy UI.

---

## 9. Backups

A database with no tested backup is not a backup.

**Schedule it** in Dokploy (Cron) or on the host:

```bash
cd /path/to/GPS_Tracer && ./scripts/backup.sh
```

It writes a compressed custom-format dump to `BACKUP_DIR`, refuses to keep a
suspiciously small one, and prunes beyond `BACKUP_RETENTION_DAYS`.

**Test a restore.** An untested restore path is not a backup:

```bash
./scripts/backup.sh list
./scripts/backup.sh restore /var/backups/gpstracer/gpstracer-2026....sql.gz
```

It stops Traccar, restores with `--clean --if-exists` so orphaned rows do not
survive, and starts Traccar again. Always copy dumps **off the server** —
another provider, object storage, your own machine. A backup on the same disk
dies with the disk.

---

## 10. Post-deploy checklist

```bash
curl -s https://fleet.example.com/api/server            # 200
curl -s -o /dev/null -w '%{http_code}\n' -X POST \
  https://fleet.example.com/api/users -H 'Content-Type: application/json' \
  -d '{"name":"x","email":"x@y.z","password":"Abc12345"}'   # 400 = closed
nc -vz fleet.example.com 5013                            # tracker port open
nmap -p 5432 fleet.example.com                           # filtered
docker compose ps                                        # both services healthy
./scripts/backup.sh                                      # produces a file
```

In the dashboard: add your first device, then work through
[`TESTING.md`](TESTING.md) before fitting anything to a truck.

---

## Updating Traccar

1. `./scripts/backup.sh`
2. Change the pinned tag in `docker-compose.yml`
3. Redeploy and **watch the logs** — schema migrations run automatically and are
   not reversible by redeploying the old tag
4. If something breaks, restore from the backup taken in step 1

Never move to `:latest`. You will not notice when it changed or what it did.
