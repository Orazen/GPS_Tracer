# Security

This deployment tracks where employees' vehicles are, continuously. In Italy that
is **personal data** under the GDPR, and worker monitoring is additionally
regulated by the *Statuto dei lavoratori* (L.300/1970, art. 4). Treat both as
requirements, not as paperwork.

---

## Exposure

Exactly two ports face the internet.

| Port | Service | Must be public? | Protection |
|---|---|---|---|
| 443 | dashboard | Yes | TLS via Dokploy, strong auth |
| 5013 | H02 tracker | Yes | none in-protocol |
| 8082 | Traccar HTTP | **No** | bound to `127.0.0.1`, proxied |
| 5432 | PostgreSQL | **No** | not published at all |

Verify from outside your network:

```bash
nmap -p 22,80,443,5013,8082,5432 fleet.example.com
```

`8082` and `5432` must show `filtered` or `closed`. If either answers, something
has changed and needs investigating immediately.

### The tracker port is inherently unprotected

H02 is a plain TCP protocol with no TLS and no authentication beyond the device
identifier in the login packet. Anyone who can reach port 5013 can attempt to
impersonate a tracker.

Practical consequences:

- If your SIM provider publishes the source IP ranges your trackers use, restrict
  5013 to those ranges at the firewall. This is the single most effective
  mitigation.
- Otherwise, accept the exposure but keep the consequence small: a spoofed
  tracker can inject false positions, it cannot reach the dashboard or the
  database.
- Never expose the dashboard's own ports to make this easier.

---

## Secrets

| Secret | Where it lives |
|---|---|
| `POSTGRES_PASSWORD` | Dokploy environment / `.env`, gitignored |
| Administrator password | password manager, never the repository |
| SIM credentials | with the SIM provider |
| Tracker config commands | vendor docs, referenced not copied |

Rules:

- **`.env` is gitignored. Never commit it.** `.env.example` holds placeholders
  only.
- Generate passwords: `openssl rand -base64 24`
- Passwords interpolated into XML must avoid `$`, `"`, `'`, `\`, and spaces. The
  rendered `traccar.xml` is XML and an unescaped `&` crash-loops the container.
- Prefer Dokploy's **Generate** button — it sidesteps escaping entirely.

### The rendered config contains the password

`traccar.xml` is regenerated at container start into a Docker named volume, with
the database password in clear text. Anyone with Docker access on that host can
read it. That is the same trust boundary as the Dokploy UI itself — restrict SSH
and Docker group membership accordingly.

```bash
docker exec gpstracer-traccar-1 cat /opt/traccar/conf/traccar.xml   # sensitive
```

---

## Accounts

**Registration is disabled.** `TRACCAR_ALLOW_REGISTRATION=false` in production,
and `TRACCAR_ALLOW_REGISTRATION=true` only during the documented first-run
bootstrap. While it is true, anyone who can reach the dashboard can create an
account.

Traccar ships with **no users**, so the bootstrap in [`DOKPLOY.md`](DOKPLOY.md#5-create-the-first-administrator)
is mandatory — not optional politeness.

Roles:

| Role | Sees |
|---|---|
| Owner (administrator) | everything, including settings and other users |
| Fleet Manager | all vehicles, reports, no user administration |

Give each named person their own account. A shared login destroys the audit trail
and means you cannot tell who did what.

---

## Passwords in Traccar

Traccar 6.16 hashes passwords with `PBKDF2WithHmacSHA256`, 200,000 iterations,
storing only the salt. That is a sound choice — there is no reason to change it.

Consequence: **do not write a script that seeds users by generating its own
hash.** A hash from any other implementation will simply fail to log in, and the
result is a deployment nobody can access. Use `scripts/create-admin.sh`, which
goes through Traccar's own API.

---

## Data retention

Position history grows fast. A truck reporting every 30 s is ~2,900 rows/day,
~1M rows/year, and each row contains a location tied to a vehicle and therefore to
an employee.

Set it deliberately:

```env
POSITION_RETENTION_DAYS=180
```

That renders `position.retention` and Traccar's scheduled cleanup enforces it.

`POSITION_RETENTION_DAYS=0` disables cleanup entirely. That is the default
behaviour of most out-of-the-box trackers and it is **not** the safe default under
the GDPR — retained, identifiable location data you have no continuing need for
is a liability with a storage cost attached.

Agree the retention period with the company, put it in writing, and tell drivers
that routes and working time are monitored. For monitoring workers, Italian law
requires the *informazione* and authorisation process, and works-council or union
involvement depending on the arrangement.

---

## Backups

- `./scripts/backup.sh` writes a compressed custom-format dump and prunes old
  ones.
- **Copy dumps off the server.** A backup on the same disk dies with the disk.
- **Test the restore.** An untested restore path is not a backup:

  ```bash
  ./scripts/backup.sh restore /var/backups/gpstracer/gpstracer-<stamp>.sql.gz
  ```

  It stops Traccar, restores with `--clean --if-exists` so orphaned rows do not
  survive, then restarts Traccar.

Dumps contain the full location history and are as sensitive as the live
database. `chmod 600`, and keep them out of the repository.

---

## Logging

`TRACCAR_LOG_LEVEL=info` in production.

`debug` is very chatty and will fill the log volume. If you turn it on
temporarily, watch the size, and expect to turn it back off.

The `gpstracer_traccar-logs` volume holds these files. Treat them as sensitive:
they contain tracker identifiers and connection events.

---

## Upgrades

1. `./scripts/backup.sh` and confirm the file is sane
2. Edit the pinned tag in `docker-compose.yml`
3. Redeploy and **read the logs**

Traccar runs Liquibase schema migrations on boot. They are **not** reversed by
redeploying the previous tag, so a bad upgrade means restoring from the backup
taken in step 1.

Never use `:latest`. An unpinned image means the upgrade happens silently on the
next restart, with no changelog read and no backup taken at the moment it matters.

---

## Checklist

- [ ] HTTPS on the dashboard, `http://` redirects
- [ ] `8082` and `5432` unreachable from the internet
- [ ] Strong generated database password, in Dokploy and out of Git
- [ ] Registration disabled
- [ ] A named administrator, plus a named account per person
- [ ] Shared logins eliminated
- [ ] `POSITION_RETENTION_DAYS` set deliberately, not left unlimited
- [ ] Retention and monitoring communicated to drivers
- [ ] Backups running, and a restore tested at least once
- [ ] Backups copied off the server
- [ ] `TRACCAR_LOG_LEVEL=info`
- [ ] SSH restricted or behind a VPN
- [ ] Traccar pinned to a specific version
