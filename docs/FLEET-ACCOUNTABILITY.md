# Driver identity and fleet accountability — what of it this system does

Source: *Driver Identity and the New Era of Fleet Accountability*, Faisal ur Rehman,
Global Trade Magazine, 14 Oct 2026 —
<https://www.globaltrademag.com/driver-identity-and-the-new-era-of-fleet-accountability/>

The article is a vendor-shaped summary of an argument that is, on the whole,
correct: **knowing where the vehicle is, is not the same as knowing who was
driving it**, and the second question is the one a transport operator gets asked
after an incident, a customer complaint or an unexplained mileage claim.

This document answers it for *this* build, claim by claim, with the status of
each one taken from the code rather than from the intention. The short version:

> **The "who was driving" half is built. The "how were they driving" half is
> deliberately absent, and in Italy that absence is a feature, not a gap.**

---

## 1. The claims, checked

| The article says | This system | Where |
|---|---|---|
| A vehicle's location alone does not tell you who drove it | ✅ **Solved for assignment, not for per-trip identity.** A driver is registered, a card is linked, a vehicle is assigned, and the assignment is **mirrored into the tracker's `driverDriverId` attribute** so the fleet screens, the unit panel and the alerts all read the same fact | Tachograph ▸ Drivers · `tacho_vehicle_assignments` · `dashboard/src/api/traccar.js` |
| Link vehicle activity to individual drivers for a clearer view | ⚠️ **Link exists; the join is manual.** The roster is what binds a name to a plate. Nothing observes *who actually got in* | see §2A |
| Support incident investigations and dispute resolution | ✅ **The evidence side is built** — dated route history with stops and arrival times, and driver activity imported from the card with the day it came from | Trail History · Tachograph ▸ Activity |
| Detect unauthorised vehicle use | ⚠️ **Partial.** An out-of-hours move raises an alert; a vehicle moved *by an unassigned driver inside working hours* raises nothing | `dashboard/src/lib/status.js` |
| Alert on unsafe driving — speeding, harsh acceleration, hard braking | ⚠️ **Speeding only, and only if you set a limit.** There is no acceleration or braking detection anywhere in the code | `ALERT_LEVEL` in `dashboard/src/lib/status.js`; `speedLimit` defaults to `0` = off |
| Businesses need clear policies on collection, storage, access and use | ✅ **Documented and partly enforced** — role separation, a written retention policy, and an audit log of every read and write of *driver* data | [`SECURITY.md`](SECURITY.md) · `tacho_audit_log` |
| Drivers should know what is collected and why | ❌ **Not built.** There is no notice screen in any surface a driver would ever see. This is the article's most transferable point and the register's most uncomfortable row | see §2D |

---

## 2. Four honest gaps the article exposes

Recorded here and in [`UNIMPLEMENTED.md`](UNIMPLEMENTED.md) rather than left as
an implication of the table above.

### §2A. Identity is an assignment, not an observation

A dispatcher writes down that Rossi has truck 07. The system then *believes* it.
There is no iButton, RFID card reader or Driver ID handshake anywhere in this
repository, and the tracker assumed here (SinoTrack ST-906L / H02) has no such
input wired. **What that means in practice:** for the "who was responsible for
this trip" question the answer is as good as the roster's discipline, and no
better. Closing it is a hardware decision — a reader on the unit, or a driver
who confirms the pairing — and then a rule that treats *assigned* and *observed*
as two different facts, which is exactly the distinction
[`DASHBOARD-SPEC.md`](../../DASHBOARD-SPEC.md) already draws for *unassigned* vs
*assigned but not displayed*.

### §2B. No unassigned-vehicle rule

The obvious rule the article's fourth section implies — *this truck moved and no
driver is assigned to it* — is not implemented. The pieces are all present
(the attribute, the alert engine, the out-of-hours rule), so this is a small
piece of work, not a research project. It is worth doing before a fleet with
shift patterns uses this, because a vehicle with a stale assignment will
otherwise look accounted for.

### §2C. Fleet data access is not audited

Every read and write of **tachograph** driver data is audited with actor, role
and source IP. Nothing records who opened a truck's trail history. The article's
transparency argument is mostly about collection, but "who looked at the route"
is the same class of question, and today it has no answer here.

### §2D. No driver-facing notice

GDPR Art. 13 requires the driver to be informed, and
[`LEGAL-ITALY.md`](../../LEGAL-ITALY.md) lists a first-launch notice screen as a
product requirement. The stack has no driver-facing surface at all (the mobile
confirm page is deferred), so this is blocked on that screen existing — not on
the policy being unclear.

---

## 3. Where this build intentionally parts company with the article

The article treats driver **behaviour scoring** as the natural next step: coach
the harsh brakers, reward the safe ones. This system does not do it, and the
reason is not effort.

Under Art. 4 of the Italian Workers' Statute (L. 300/1970), continuous
monitoring of a worker — including by instrument — needs a union agreement or
INL authorisation, and the Garante has repeatedly held that consent is not a
valid basis inside an employment relationship. A behaviour score is not a
by-product of a tracking system; it is the thing that turns one into a
monitoring system. So:

| The article's direction | What is built instead |
|---|---|
| Score each driver's acceleration, braking, cornering | Nothing. Not built, not planned here |
| Rank drivers by risk | Nothing |
| Continuous monitoring, all hours | An out-of-hours **alert** with the name hidden by default; retention capped by `POSITION_RETENTION_DAYS` |
| "Telematics as a safety culture tool" | Safety **zones** (no-go areas, harsh terrain) and proof-of-delivery — the permitted Art. 4 purposes |

That is not a limitation to apologise for in an Italian sale; it is the answer to
the first question a works council asks, and it can be given in one sentence
because it is true of the software rather than of a policy document.

---

## 4. What is worth taking from the article

Three points, in order of how much they would change this build:

1. **The unassigned-vehicle rule** (§2B). Cheapest real improvement, and the one
   the article's "unauthorised use" section is actually about.
2. **The identity join.** Everything downstream — investigations, disputes,
   unauthorised use — inherits its accuracy from whether *assigned* means
   *observed*. The tachograph registry already closes the assignment history;
   the missing half is on the unit.
3. **Access transparency** (§2C). The audit machinery exists for one data set
   and should not stop there.

What is **not** worth taking: the behaviour-scoring programme. It is the part of
the article that sells best and survives an Italian labour inspection worst.

---

## Sources

- Global Trade Magazine, *Driver Identity and the New Era of Fleet
  Accountability*, 14 Oct 2026 (link above)
- Garante, provv. n. 7 del 16 gennaio 2025 — geolocalizzazione di lavoratori su
  veicoli aziendali
- Art. 4 L. 300/1970; Circolare INL n. 2/2016; INL nota 25 settembre 2024
- GDPR Arts. 5, 6, 13, 25, 35, 88 — see [`LEGAL-ITALY.md`](../../LEGAL-ITALY.md)
