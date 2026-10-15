# Tachograph service

Uploads driver-card and vehicle-unit downloads, normalises their activity, and
reports driving time. Runs as two containers: an API and a worker.

```
                 ┌─────────────────────────────────────────────┐
 driver card ──▶ │  tacho-api   (loopback :8084, token-gated)  │
 .DDD upload     │    hash · store original · dedupe · queue   │
                 └────────────────────┬────────────────────────┘
                                      │ tacho_imports (status='pending')
                 ┌────────────────────▼────────────────────────┐
                 │  tacho-worker   (no ports, no network I/O)  │
                 │    claim · parse · normalise · persist      │
                 └────────────────────┬────────────────────────┘
                                      │
                 ┌────────────────────▼────────────────────────┐
                 │  PostgreSQL (tacho_* tables, private)       │
                 └─────────────────────────────────────────────┘
```

---

## 1. Why two containers

The specification requires parsing to be kept out of the web request process. Two
processes from one image is the honest way to do that:

- A parser bug, a hang, or an OOM cannot take the API down with it.
- A slow parse cannot hold an upload connection open.
- The upload endpoint returns in milliseconds regardless of file complexity.
- The image is shared, so the parser that runs in the worker is byte-for-byte the
  one the API was tested against.

**Why PostgreSQL instead of a message broker.** The `tacho_imports` table *is* the
queue, claimed with `SELECT ... FOR UPDATE SKIP LOCKED`. Several workers can run
concurrently without a broker and without two of them taking the same file. A
broker would be a second moving part to back up, monitor and secure, and at this
throughput it buys nothing.

**Stale-lease recovery.** A worker killed mid-parse leaves a row in `processing`. Its
lease (`TACHO_WORKER_LEASE_MINUTES`, default 15) expires and another worker reclaims
it. Nothing is stranded, and nothing is processed twice.

---

## 2. The import lifecycle

| Status | Meaning | Terminal? |
|---|---|---|
| `pending` | Stored and queued. Nobody has parsed it. | No |
| `processing` | Claimed by a worker, under lease. | No |
| `done` | Parsed. Activity written. | Yes |
| `failed` | A parse attempt failed; may be retried until the attempt budget is spent. | No |
| `rejected` | Attempt budget exhausted. Not retried. The error is preserved. | Yes |
| `duplicate` | Identical content (SHA-256) was already imported successfully. | Yes |

**Duplicates are recorded, not hidden.** You asked for import history; "the same card
was uploaded twice" is part of that history. A duplicate row keeps its filename,
uploader, timestamp and a `duplicate_of` pointer, and contributes **no** activity rows
of its own — so nobody's totals get double-counted.

**A failed file can be re-uploaded.** Deduplication only matches against imports that
succeeded. Otherwise a transient error would permanently poison those exact bytes.

**Failures never half-write.** Days and changes are written in one transaction. A
file contributes all of its rows or none: half a day's activity is worse than a
failed import, because it looks like data.

---

## 3. Storage of originals

Layout: `<storage_dir>/objects/<first 2 hex>/<sha256>.ddd`, mode `0700`/`0600`,
content-addressed.

- The **hash is computed from the bytes**; a caller-supplied hash is verified, never
  trusted.
- Writes go to a temporary file and are renamed into place, so an interrupted write
  cannot leave a truncated object that later looks like a valid cache hit.
- **There is no endpoint that returns file bytes.** The specification's "do not expose
  original files through public URLs" is enforced by omission, not by an access check
  that could be got wrong. No query in `repository.py` even selects `stored_path`.

> ⚠️ **Operational consequence.** The `tacho-data` volume and the `tacho_` tables must
> be backed up **together**. Restore the database without the volume and imports
> reference files that are gone — which `scripts/backup.sh` will not detect for you.
> See §7.

---

## 4. API

All routes require `X-Service-Token` (or `Authorization: Bearer`) **and**
`X-Actor` with `X-Actor-Role`. Roles: `owner`, `fleet_manager`, `viewer`. Driver
personal data is readable only by `owner` and `fleet_manager`; an unknown or missing
role resolves to `viewer`, never to a privileged one.

| Method | Path | Role | Purpose |
|---|---|---|---|
| `GET` | `/healthz` | none | Liveness. Says nothing about data. |
| `GET` | `/api/meta` | any | Versions, parser adapters, the unvalidated caveat. |
| `POST` | `/api/imports` | owner, fleet_manager | Upload a `.DDD`. Returns `202`. |
| `GET` | `/api/imports` | owner, fleet_manager | Import history, filterable by status/card/date. |
| `GET` | `/api/imports/{id}` | owner, fleet_manager | One import: status, warnings, evidence, day count. |
| `GET` | `/api/imports/{id}/timeline` | owner, fleet_manager | Every activity change in the file. |
| `GET` | `/api/drivers` | owner, fleet_manager | Driver-**card** registry. **Audited.** |
| `GET` | `/api/people` | owner, fleet_manager | The people: name, employer reference, current card, current vehicle. **Audited.** |
| `POST` | `/api/people` | owner, fleet_manager | Register a person; optionally links a card from the registry in the same call. **Audited.** |
| `POST` | `/api/people/{id}/active` | owner, fleet_manager | Take a person out of the assignable list, or put them back. **Audited.** |
| `GET` | `/api/card-assignments` | owner, fleet_manager | Who held which card, and when. |
| `POST` | `/api/card-assignments` | owner, fleet_manager | Link a card to a person, closing what it replaces. **Audited.** |
| `GET` | `/api/vehicle-assignments` | owner, fleet_manager | Who drove which vehicle, open rows first. |
| `POST` | `/api/vehicle-assignments` | owner, fleet_manager | Record that a driver is in a vehicle from a date. **Audited.** |
| `POST` | `/api/vehicle-assignments/{id}/close` | owner, fleet_manager | End an assignment without naming a replacement. **Audited.** |
| `GET` | `/api/days` | owner, fleet_manager | Normalised days with per-activity totals. |
| `GET` | `/api/coverage` | owner, fleet_manager | Which days exist, which are missing, what that invalidates. |
| `GET` | `/api/summary/daily` | owner, fleet_manager | Days plus Monday-based weekly roll-ups. |
| `GET` | `/api/reports/activity.csv` | owner, fleet_manager | CSV export carrying its own provenance. |
| `POST` | `/api/calculations` | owner, fleet_manager | Run and store a driving-time calculation. |
| `GET` | `/api/calculations[/{id}]` | owner, fleet_manager | Stored calculation runs. |
| `GET` | `/api/audit` | **owner only** | Audit log. |

### Two different questions, two different endpoints

`/api/drivers` returns **cards** this service has seen; `/api/people` returns the
**people** who hold them. They are separate tables because a driver keeps their
card when they change employer and can be reissued one after a replacement, so
"who was driving" has to survive a renewal. `/api/drivers` keeps its name and its
shape: it is already published and its client reads `driver_cards`, and renaming a
shipped endpoint to make the newer model tidier would break the older caller for a
cosmetic gain.

### Assignments: closed, never deleted, and not more than one at a time

A new assignment closes the driver's previous open one rather than deleting it, and
the closed row is what answers "who was driving that truck on the 3rd". The
invariants are enforced twice -- by `tacho/registry.py`, and by partial unique
indexes in `migrations/0004_assignment_invariants.sql`, because a module that only
*remembers* to close the previous row is one refactor away from two open rows.

There is deliberately **no** unique index per vehicle. Art 8(5) multi-manning puts
two drivers in one cab, and a constraint that made the correct case impossible to
record would be worse than none; a vehicle therefore keeps however many open
assignments it has, and the console shows them all.

Two consequences worth knowing before reading the data:

* A same-day reassignment closes the previous row **on the day it started**
  (`GREATEST(assigned_from, new_start - 1 day)`), which is the only value that both
  satisfies the table's `assigned_to >= assigned_from` check and leaves exactly one
  row open.
* `vehicle_ref` is the tracker's **uniqueId**, not the vehicle's name. A truck
  renamed in the tracker console must not detach from its own history.

### The CSV report carries its provenance

```
# generated_at_utc,2026-10-13T10:02:52+00:00
# driver_key,card:IT00000000000000
# period_start,2026-10-05
# rules_version,eu-561-2006/2026.1
# engine_version,driving-time/0.1.0
# parser_version,gen1-0.1.0
# calculation_validated_against_reference,false
# days_with_a_record,5
# days_missing,5
# missing_days,2026-10-10;...
```

A spreadsheet that leaves the building without saying which rules version and which
coverage produced it cannot be checked later, and will be quietly wrong the first
time somebody re-runs it against different data.

---

## 5. The parser, and the honest limits of it

`tacho/tacho/parsers/gen1.py` is a **clean-room GEN1 driver-card parser**, written
from Annex 1B Appendix 1 (data dictionary) and Appendix 7 (data download / TREP) of
Commission Regulation (EC) No 1360/2002 as amended, with no code taken from any
existing parser. See `docs/LICENCES.md` §5 for why the obvious candidate was rejected.

### Verified against the regulation and exercised by tests

- The card container: a flat concatenation of `FID(2) || suffix(1) || length(2, BE)
  || value` (Appendix 7 §3.4.2). `suffix 0x00` = file data, `0x01` = that file's
  signature.
- `ActivityChangeInfo`, 16 bits `scpaattttttttttt`: slot, crew, card-present,
  activity (00 rest, 01 availability, 10 work, 11 driving), minutes since 00:00.
- `CardActivityDailyRecord`: previous-record length, record length, `TimeReal` date,
  daily presence counter, day distance, then the change set.
- `CardDriverActivity`: oldest/newest pointers plus the **cyclic** record buffer.
- `CardIdentification`, `DriverCardHolderIdentification`, `TimeReal`, `Datef`,
  `DailyPresenceCounter`, `Distance`, `Name`.

### Two things are deliberately NOT guessed

**The GEN1 card EF identifiers.** The regulation's Appendix 2 EF table could not be
retrieved during research. Rather than hard-code identifiers from secondary sources,
the activity file is located **by structure**: any TLV value that parses as a
well-formed `CardDriverActivity` is used, and the tag values are treated as hints that
only break ties. `test_structural_location_does_not_depend_on_the_tag` proves this by
rewriting the activity object with a deliberately wrong identifier and asserting the
parser still finds it. The discovered FID is reported in `raw_evidence` and in a
warning, for checking against a real card.

**Vehicle-unit downloads.** A VU download is *not* a TLV container — it is a stored
positive-response stream (`SID 0x76` + one-byte `TREP` + data), and the body layout of
each TREP could not be verified. The parser therefore **detects a VU file and refuses
to decode it**, returning a warning and zero days. Producing plausible-looking wrong
driving hours from an unverified layout is the one outcome that must never happen
here. `TREP 06` (a card download embedded in a VU download) *is* decoded, because that
inner blob keeps the card format.

Note also that TREP is one byte, not two, and the mapping is `01` overview,
`02` activity for a date, `03` events/faults, `04` detailed speed, `05` technical data,
`06` card download. "TREP 01 = daily activity" is a common and wrong assumption.

### Verification status

| Claim | Status |
|---|---|
| Container walk, cyclic buffer, bit layout: internally consistent | ✅ **tested** — 353 tests |
| Malformed, truncated and non-tachograph files are contained | ✅ **tested** |
| Duplicates detected and recorded | ✅ **tested** against PostgreSQL |
| **Reads a real driver card** | ❌ **NOT RUN** — no lawfully obtained real `.DDD` exists here |
| **Reads a real vehicle-unit file** | ❌ **NOT IMPLEMENTED** — refused by design |
| GEN2 / GEN2v2 | ❌ **NOT IMPLEMENTED** — refused; the formats differ enough that GEN1 offsets would produce confidently wrong hours |
| External parser adapter: JSON mapping and every failure mode | ✅ **tested** — 22 tests drive it with stub commands |
| External parser adapter against a **real** parser | ❌ **NOT RUN** — no external binary is installed, so no test exercises `tachograph-go` itself |

Every fixture in `tacho/tacho/fixtures/` is **generated** from the regulation by our
own writer. They prove internal consistency; they do **not** prove interoperation with
a real tachograph. No test in this repository claims otherwise, and the docstrings say
so.

---

## 6. Configuration

See `.env.example` for the annotated list. The two that matter:

| Variable | Why |
|---|---|
| `TACHO_API_TOKEN` | **MANDATORY.** The API serves driver personal data and refuses to start without it. |
| `TACHO_EXTERNAL_PARSER` | Optional. The wiring point for `tachograph-go` (MIT) to add VU/GEN2 support. Empty is a supported configuration. |

Startup validation refuses to run if the token is missing or short, if the storage
directory is inside a `.git` directory, or if the database URL is not PostgreSQL.
Same discipline as the Traccar entrypoint: **fail loudly at startup rather than come
up looking healthy.**

---

## 7. Operations

```bash
# Start everything (Traccar, database, the two tacho containers)
docker compose up -d

# Drain the queue once and exit: useful from cron, and for verifying a deployment
docker compose run --rm tacho-worker python -m tacho.worker --once

# Health
curl -s http://127.0.0.1:8084/healthz

# Upload
curl -X POST http://127.0.0.1:8084/api/imports \
  -H "X-Service-Token: $TACHO_API_TOKEN" \
  -H "X-Actor: dispatcher" -H "X-Actor-Role: fleet_manager" \
  -F "file=@driver.ddd" -F "declared_kind=driver_card"

# Import history
curl -s "http://127.0.0.1:8084/api/imports?status=failed" \
  -H "X-Service-Token: $TACHO_API_TOKEN" -H "X-Actor: dispatcher"
```

### Re-parsing after a parser upgrade

Parsing is not destructive and imports are immutable, so the safe procedure is:

1. Upgrade the image (the parser version is stored on every import).
2. Identify imports whose `parser_version` is older than the current one.
3. **Upload the original file again.** Dedupe will mark it a duplicate — which is
   correct — so instead set the original row back to `pending` and let the worker
   re-process it. The new parse replaces that import's activity rows in one
   transaction; other imports are untouched.

Do **not** edit a row's `parser_version` after re-parsing. It is the record of what
produced the rows currently attached to it.

### Retention

Driver data is personal data. `tacho_imports`, `tacho_activity_*` and the
`tacho-data` volume all need a retention policy — see `docs/SECURITY.md § Data
retention`. Nothing in this service deletes anything automatically.

---

## 8. Testing

```bash
cd tacho

# Pure-logic suite: no database, no network, no third-party services
python -m pytest tests/ -q

# Database-backed suite against a throwaway PostgreSQL
docker run -d --rm --name tacho-test-db -p 127.0.0.1:55432:5432 \
    -e POSTGRES_PASSWORD=test -e POSTGRES_USER=test -e POSTGRES_DB=test postgres:16-alpine
TACHO_TEST_DATABASE_URL=postgresql://test:test@127.0.0.1:55432/test \
    python -m pytest tests/ -q
```

**Never point `TACHO_TEST_DATABASE_URL` at a real deployment.** The suite truncates
the `tacho_*` tables between tests.
