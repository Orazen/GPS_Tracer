# Licence audit

Required by the specification: *"Audit the licenses of every dependency before
commercial integration."*

Verdict up front: **the platform ships with no copyleft obligation in its own
code.** Everything added by this project is Apache-2.0-compatible or more
permissive. One component — Traccar — is GPL-2.0 and is used as an unmodified
separate service, which is the arrangement that keeps the obligation answerable.
The one genuinely risky temptation (an AGPL-3.0 tachograph parser) was deliberately
not taken.

This is an engineering audit, not legal advice. Items marked ⚠️ deserve a lawyer's
eye before you sell hosting to third parties.

---

## 1. Runtime components

| Component | Version | Licence | How it is used | Obligation |
|---|---|---|---|---|
| Traccar | 6.16 (`traccar/traccar:6.16-alpine`) | **GPL-2.0** | Run unmodified as its own container | ⚠️ see §3 |
| PostgreSQL | `postgres:16-alpine` | PostgreSQL Licence (BSD-style) | Separate container | None beyond notice |
| Docker / Compose | host-provided | Apache-2.0 | Orchestration | None |
| PostgreSQL JDBC driver | bundled in the Traccar image | BSD-2-Clause | Traccar's own dependency | None |
| Java runtime | bundled in the Traccar image | GPL-2.0 **with Classpath Exception** | Runs Traccar | Classpath Exception removes the linking question for Traccar's own code |

## 2. Application code in this repository

### Tachograph service (`tacho/`)

| Component | Licence | Notes |
|---|---|---|
| Our own code | Apache-2.0 (inherits this repository) | — |
| FastAPI | MIT | HTTP framework |
| Uvicorn | BSD-3-Clause | ASGI server |
| psycopg (psycopg 3) | LGPL-3.0 | ⚠️ see §4 |
| **psycopg-binary** | LGPL-3.0 | Prebuilt binary wheel — see §4 |
| Pydantic | MIT | Validation |
| python-multipart | Apache-2.0 | Multipart uploads |
| pytest, httpx | MIT / BSD-3-Clause | Test-only, not shipped in the image |

Deliberately **zero** runtime dependencies in the part that matters: the GEN1
parser, the activity model and the driving-time rules engine are **pure Python
standard library**. That is not an accident — it means the code that decides
whether somebody's driving hours are right has no third-party licence attached to
it at all, and no upgrade can silently change its behaviour.

### Nothing else was added

No Node, Go, Rust or Java dependency was introduced. The dashboard (Phase 2) is not
built yet; when it is, its dependencies need auditing in the same way — see
`docs/UNIMPLEMENTED.md`.

---

## 3. ⚠️ Traccar is GPL-2.0 — what that does and does not mean

Traccar is **not modified** by this project. It runs as a pinned upstream image with
configuration injected at container start (`traccar/config/entrypoint.sh` renders
`conf/traccar.xml` from environment variables).

Why that arrangement was chosen:

- GPL-2.0 obliges you to provide source **when you distribute the program**. Running
  it on a server you own, for your own fleet, is not distribution.
- Hosting it for third parties is also not distribution in the GPL sense — GPL-2.0
  has no network clause. So the "you must publish your platform" fear is unfounded
  here.
- The real practical duties: **offer the Traccar source** to anyone you *do* ship a
  copy to (for example, if you ever hand a client the whole image), and **do not
  statically link or vendor modified Traccar sources into your own product**.

What would change the analysis, and must therefore not be done casually:

- Patching Traccar's Java sources and shipping a rebuilt image to a client.
- Copying Traccar code into this repository.
- Bundling Traccar into a product you distribute.

**If any of those become necessary, treat it as a licensing decision, not a
refactor.** The safe recipe is: keep Traccar upstream, pin the version, integrate
over its REST API and WebSocket only.

---

## 4. ⚠️ psycopg is LGPL-3.0

psycopg 3 is LGPL-3.0. It is used as an **unmodified library imported at runtime**,
not statically linked, not modified. LGPL-3.0 permits that without any obligation on
our own code, provided:

- we do not modify psycopg,
- users can replace it (installing a different psycopg into the image is possible,
  so this is satisfied).

`psycopg[binary]` ships prebuilt wheels that bundle libpq. That is a different
packaging question from the licence of the source, and it is the version that is
pinned. If you want to remove all doubt, install the source distribution against
the system libpq instead of the binary wheel — it costs a `libpq-dev` build
dependency and changes nothing else.

---

## 5. The tachograph parsers, and why the obvious choice was rejected

This is the most important section of this document, because the specification
named `tachoparser` as a candidate and asked for the obligations to be reviewed
before incorporating it.

| Project | Language | Licence | Status | Verdict |
|---|---|---|---|---|
| [`traconiq/tachoparser`](https://github.com/traconiq/tachoparser) | Go | **AGPL-3.0** | Active, no tagged releases | ❌ **not used** — see below |
| [`way-platform/tachograph-go`](https://github.com/way-platform/tachograph-go) | Go | **MIT** | Active, releases + Gen2v2 work | ✅ the recommended external parser |
| [`Syax89/DDDTachograph_Reader`](https://github.com/Syax89/DDDTachograph_Reader) | Python | **MIT** | Young, self-described unvalidated | ⚠️ optional, verify first |
| ReadESM (SourceForge) | C++ | GPL-2.0 | Beta, last activity 2023 | ❌ copyleft, legacy |
| [`baekgaard/readesm`](https://github.com/baekgaard/readesm) | C++ | GPL-3.0 | Stale fork (2017) | ❌ stale and copyleft |
| [`jugglingcats/tachograph-reader`](https://github.com/jugglingcats/tachograph-reader) | C# | MIT | Last activity 2020 | 📖 GEN1 reference only |
| [`defkode/esm-reader`](https://github.com/defkode/esm-reader) | Ruby | MIT | **Archived** 2024 | ❌ archived |

### Why `tachoparser` was not used

Three reasons, any one of which is sufficient:

1. **AGPL-3.0 §13 is triggered by *modification*, not by hosting.** Running an
   unmodified parser privately does not force you to publish your platform. But
   §13's trigger is easy to hit: the first upstream fix you carry locally, or the
   first adapter you patch in, and the source-offer obligation attaches to that
   modified version — for *all* users interacting with it remotely, including your
   own staff. A separate process is helpful evidence, but it is **not a legal
   boundary**; "combined work" is fact-specific.
2. **Its documented coverage contradicts its own README.** The README claims VU and
   driver-card support across Gen1, Gen2 and Gen2v2, while the same README's TODO
   list still carries parsing for each of those combinations as outstanding, along
   with signature verification and tests. Coverage has to be *tested*, not read off
   a description.
3. **There is a permissive alternative.** `tachograph-go` is MIT, actively
   maintained, and has release notes showing real Gen2v2 work.

### What this project does instead

1. **A clean-room GEN1 driver-card parser**, written from the regulation, in this
   repository (`tacho/tacho/parsers/gen1.py`). No copyleft attaches to it, and its
   limits are documented rather than implied.
2. **An external-parser adapter** (`tacho/tacho/parsers/external.py`) that shells out
   to any command reading a file on stdin and writing JSON on stdout. This is the
   supported wiring point for `tachograph-go`, set through `TACHO_EXTERNAL_PARSER`.
   Nothing copyleft is linked into this process, and an AGPL parser placed behind it
   is at least *architecturally* separable — with the caveat in §5.1.

#### 5.1 ⚠️ If you ever do deploy an AGPL parser behind the adapter

Do not rely on the process boundary alone. Either (a) do not modify it, and record
that decision; or (b) accept the §13 source-offer obligation for the modified
version and publish that parser's source; or (c) get legal review on whether your
integration is a combined work. This is exactly the sort of question the README's
licence section should not answer by assumption.

---

## 6. Data licences: the map

Not a code dependency, but a licence obligation and easy to overlook.

| Source | Licence | Constraint |
|---|---|---|
| OpenStreetMap tiles | ODbL 1.0 | Attribution required; bulk downloading is prohibited by the [tile usage policy](https://operations.osmfoundation.org/policies/tiles/) |
| Traccar's default map | see Traccar config | Inherits whatever provider it is pointed at |

**Do not put OSM's public tile server in front of a commercial dashboard at fleet
scale.** It is a community service, and the usage policy prohibits exactly that.
Point the map at a paid provider or self-host tiles — this is a deployment decision
and belongs in `docs/DOKPLOY.md` when the Phase 2 dashboard is built.

---

## 7. Summary for a commercial decision

| Question | Answer |
|---|---|
| Can we sell this as a hosted service? | Yes. No component imposes a network-copyleft on our own code. |
| Can we distribute an appliance/VM to a client? | Yes, but you must then provide Traccar's source (GPL-2.0). |
| Can we modify Traccar and ship it? | Only if you accept GPL-2.0 on that modification and publish its source. |
| Are we forced to open-source the tachograph service? | No. It is our code, and it contains no copyleft dependency. |
| Biggest residual risk | ⚠️ The AGPL parser temptation (§5), and OSM tile policy at scale (§6). |
