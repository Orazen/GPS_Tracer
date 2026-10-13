# Live tachograph integration — go/no-go

Phase 6 says: *do not assume GPS hardware can read the tachograph; investigate the
actual manufacturer, model, ITS interface, remote-download options, company-card
authentication and API access first; document compatibility, price and recurring
fees before purchase.*

This document is that investigation. **No live integration has been built, and no
gateway hardware has been purchased or committed to.** Nothing in the platform claims
live tachograph functionality.

---

## Verdict

| Goal | Verdict |
|---|---|
| Get **scheduled remote `.DDD` downloads** without buying a tachograph-analysis suite | ✅ **Go**, via a third-party remote-download service with a documented API |
| Get **live driving-time values** directly from the tachograph | ⚠️ **Go only via the consent-gated ITS interface**, and it is not the same data |
| Read the tachograph through **our existing GPS tracker** | ❌ **No** — not with anything currently specified for this fleet |
| Use **roadside DSRC** to collect our own data | ❌ **No** — that channel is for enforcement |

The honest summary: **a small Italian carrier can get remote files without joining a
single vendor's ecosystem, but cannot skip the ecosystem's prerequisites** —
compatible onboard equipment, a company card in a reader, a service that manages
authentication, and somewhere to archive and interpret the result.

---

## 1. How remote download actually works

Two different things get called "download", and they have different costs:

**Manual download.** Someone physically attends the vehicle with a download key or
card reader, or removes the driver card and reads it at a desk. This is what the
current platform already supports: upload the `.DDD` through the tachograph service.

**Remote download.** A telematics unit wired to the tachograph, plus a back-end that
requests files over mobile data. It is **scheduled or requested, not a continuous
stream**.

The flow, and the part that surprises people:

1. A **company card is placed in a reader** at the company's premises, or in a hosted
   card-reader arrangement.
2. The service authenticates the company against the tachograph.
3. A compatible onboard device performs the download.
4. The file goes to a portal, or to an integration endpoint.

**The company card is not optional and not a one-off.** It must remain valid and
readable; an expired or removed card is the most common cause of downloads silently
failing. Any workflow built on this needs card-expiry monitoring, because the failure
mode is absence of data rather than an error.

Also worth knowing: the vehicle usually has to be driving or have the ignition on for
a download to start.

### Compatibility is per model *and revision*, not per brand

| Family | What the sources support |
|---|---|
| Continental/VDO **DTCO 1381** | release 1.3a, 1.4 or later |
| Continental/VDO **DTCO 4.0 / 4.1** | supported, but **4.0 is not one uniform case** — a documented fault could break remote download after an authentication attempt with an expired company card, fixed in 4.0f |
| Stoneridge **SE5000** | release 7.1 or later |
| ACTIA | specific firmware/part references, not "all ACTIA" |

**Action: read the model and software revision off each truck's tachograph label or
technical-data printout before talking to any vendor.** A brand name is not a
compatibility guarantee, and DTCO 4.0/4.1 in particular needs written confirmation.

---

## 2. Vendor options

"Public API" below means public documentation was found. It does **not** mean free,
self-serve, or automatically enabled on an account.

| Provider | Tachograph function | Integration | Price |
|---|---|---|---|
| **Teltonika TachoSync** | Remote VU + card download for eligible Teltonika trackers; company-card authentication via its Company Card Authenticator | **Documented REST API**, scoped API keys | Credits: **one credit per unique active tracker per month**; no published currency price per credit |
| **VDO Fleet** | Remote DL 4G + cloud tachograph management | **Extract service exports tachograph data to a third-party backend via API** — but on the Professional tier | Quote |
| **Cartrack** | Public developer docs listing "Download Tachograph File" and "Get All Tachograph Files" | **Authenticated REST API documented** | Not verified for an Italian plan |
| **TachoScan / INELO** | Analysis product | An API documentation site exists | Endpoints, access conditions and price not verifiable |
| **Transics / ZF TX Connect** | Remote download well documented | Public tacho-file API **not** established | Quote |
| **Microlise** | Remote download, can forward to an analysis provider | Public API not verified | Quote |
| **Fleetboard** | Daimler | API exists, **SOAP**, depends on booked services | Quote |
| **DKV LIVE** | Download and store, driving/rest data | Public tacho API not verified | Quote; one-month trial |
| **Frotcom** | Remote download; integrates with VDO Fleet | Public tacho API not verified | Quote |
| **Trimble** | Remote download via onboard computers | Public API not verified | Quote |
| **ACTIAFleet** | Manual + remote download, company-card management, PDF/XLS/CSV export | No public API found | Quote |

**Finding: public pricing is the exception, not the rule.** Only TachoSync publishes a
clear billing model. I found no defensible cross-vendor "€X per vehicle per month"
comparison, so **do not budget from this table** — use it to pick whom to quote.

---

## 3. The two interfaces that get confused with remote download

**Roadside DSRC (Reg 165/2014 Art 9) — ❌ not usable for this.** It exists so control
authorities can perform remote early detection. The data exchanged is limited to
specified manipulation/misuse indicators, retention is restricted, and the regulation
says it cannot by itself produce a fine. **It is not a fleet-data channel. Do not plan
around it.**

**The ITS interface (Reg 165/2014 Art 10) — ⚠️ usable, but different and
consent-gated.** It gives an external device selected *operational* data in real time.
It requires that access to personal data — including geolocation — follow the driver's
**verifiable consent**, which the driver can refuse and later revoke.

Two consequences for the product:

1. **ITS data is not the same as a `.DDD` file.** It exposes selected current values,
   not the mass-memory archive. It cannot replace file-based analysis.
2. **Consent is per-driver and revocable.** A feature built on it must have a
   designed behaviour for the moment consent is withdrawn, and for a driver who never
   gives it. That is a product decision, not a driver-side detail.

Do **not** treat an advertised K-line port, a "CAN" claim, or a general telematics API
as equivalent to remote tachograph-file downloading.

---

## 4. Can our GPS tracker read the tachograph?

**Not with anything currently specified for this fleet.** No model in the hardware
documents makes a tachograph-read claim, and the general position is that an ordinary
GPS tracker cannot do this.

Trackers that *do* claim it, and what they require:

| Vendor | Devices | Requirement |
|---|---|---|
| Teltonika | FMC650, FMM650, and specific FMC640/FMB640/FMB641 | TachoSync account + company-card authenticator; Smart Tachograph v2 support is limited to named devices and firmware |
| Ruptela | HCV5, HCV5 Lite | Per-revision VU support list |
| Queclink | **GV355CEU** (brochure explicitly claims tachograph CAN/K-line, live data and remote DDD download) | Model-specific; **not verified** for our fleet |
| Concox | — | **No authoritative source found. Do not assume any model.** |

Note the pattern: support is a *model-plus-firmware* property. Even Teltonika, which
publishes the clearest matrix, limits v2 support to specific devices.

**Arithmetic worth doing before buying anything:** switching the fleet to
tachograph-capable trackers means replacing hardware *and* adding a per-vehicle
monthly service. Compare that against keeping manual card downloads, which cost
staff time and nothing else. For 1–5 vehicles, manual download plus this platform's
import path is very likely the better trade — the volume does not justify the
integration.

---

## 5. What would have to be true to build this

Answer these before writing an adapter. Each is a gate, not a task.

1. **Which trucks, exactly?** Tachograph brand, model, generation and software
   revision, per vehicle. Without this, compatibility cannot be assessed at all.
2. **Who holds the company card, and where does the reader live?** Who monitors its
   expiry? What is the procedure when the card is away from the office?
3. **Files or live values?** These are different integrations with different data.
   Decide, and write it down.
4. **What is the integration contract?** A public API, a booked plan, or a partner
   agreement? Which fields? What rate limits, retention and cost?
5. **What happens when a download fails?** Alerts, retries, audit history, and a
   manual fallback. Silent failure is the default behaviour and must be designed
   against.
6. **Who is responsible for the analysis?** Collecting files is not interpreting
   them. If this platform interprets them, its output must be validated — see
   `docs/DRIVING-TIME.md` §7.

---

## 6. Recommended path, in order

1. **Do nothing for now.** Manual `.DDD` upload through the tachograph service already
   works, is tested, and costs nothing per month. Run it for a month and find out
   whether the fleet's actual pain is collection frequency or analysis quality. It is
   usually the latter.
2. **If collection is the pain**, get written quotes from **TachoSync** (clearest
   published model, documented API) and **VDO Fleet Professional** (documented export
   to a third-party backend). Ask both for an Italian-fleet price and their VU
   compatibility list.
3. **Collect the fleet's tachograph details first** (§5.1) and give them to both
   vendors. A quote without the model and revision list is not a quote.
4. **Then build the adapter** behind `TACHO_EXTERNAL_PARSER` or as a new gateway
   module, and treat the download service as untrusted input exactly like an upload.

Everything in the export path must also be **tested against a real download**. Until
then it is a plan, not a feature, and it must not be described as working.

---

## 7. Status register

| Item | Status |
|---|---|
| Investigation | ✅ **done** (this document) |
| Gateway hardware purchased or committed | ❌ **not purchased** |
| Live integration implemented | ❌ **not implemented** |
| Adapter interface for external parsers | ✅ **implemented** (`TACHO_EXTERNAL_PARSER`) |
| ITS-interface integration | ❌ **not implemented** |
| Driver-consent handling | ❌ **not implemented** — required before any ITS work |
| Company-card expiry monitoring | ❌ **not implemented** — required before any remote download |
| Live tachograph functionality claimed anywhere in the UI | ✅ **no** — nothing claims it |
