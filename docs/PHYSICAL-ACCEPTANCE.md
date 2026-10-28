# Physical acceptance checklist — server path and tracker

> **Status: PHYSICAL HARDWARE VERIFICATION — NOT RUN.**
> Nothing in this file has been executed against a real tracker, SIM, antenna or
> vehicle. The software path (the tool, its unit tests, and an offline replay of
> simulator packets) has been run; the physical steps below have not. Do not record
> any of them as passed until someone has done them on the unit and written down
> what they saw.

This checklist is for the person who installs the first tracker. It is the operator's
half of `docs/TESTING.md`: that document covers *what* to test, this one covers *which
server-side settings must be right first* and *which command to run to see each one*.

---

## 0. What the tooling does and does not do

`scripts/connect-tracker.py` is the only automation involved, and it is deliberately
narrow.

| It does | It does not |
|---|---|
| Print the SMS sequence for the tracker (`--print-sms`) | **Send any SMS.** You send them, by hand, from a phone. |
| Read the published H02 port from `docker inspect` (`--check`) | Change `.env`, `docker-compose.yml`, or any production configuration |
| Test TCP to the server from *this* machine (`--server`) | Prove the public path. Only an outside test does that (see §1). |
| Create or update **one Traccar device record** through Traccar's API, when run without `--check` or `--print-sms` | Auto-accept an unknown IMEI. Adopting an identifier needs `--adopt-seen-id`, typed by you. |
| Watch the log and the API and report five checks | Reboot a service, restart a container, or touch a firewall |

The device-record write is the only change the tool makes to a running system, and it
happens only when you run it without `--check` or `--print-sms`. Re-running it does not
create a second record: it finds the record by IMEI and updates it.

Nothing in this checklist is run automatically. Every command in §8 is for the operator
to read, approve and run.

---

## 1. Port mapping: public 5013 → container 5013

The tracker connects to **the host's** port. Traccar listens on **5013 inside the
container**. The compose file maps one to the other:

```yaml
# docker-compose.yml, traccar service
- "${H02_PORT:-5013}:5013"
```

The host side is configurable; the container side is fixed. Mapping the host port
onto itself (`"${H02_PORT}:${H02_PORT}"`) is the bug in `docs/UNIMPLEMENTED.md` §7.8:
with `H02_PORT=5093` it publishes Traccar's *watch* listener, and the stack passes every
healthcheck while decoding nothing.

- [ ] The container publishes exactly one H02 mapping, and its container side is 5013.
- [ ] The host side equals `H02_PORT` in `.env` (default 5013).
- [ ] Only one Traccar stack is running on this host that publishes the same host port.

Checks (read-only):

```bash
docker compose ps
./scripts/connect-tracker.py --check
```

`--check` reports `host <N> -> container 5013/tcp` on success. It exits **1** when it
cannot find or inspect a Traccar container, because a mapping that was never checked is
not a pass.

---

## 2. Host firewall: inbound TCP to the H02 port

The host port must be reachable from the internet, through **both** the host firewall
and any cloud firewall or security group in front of it. Opening one and not the other
looks identical from the tracker's side: the connection is silently dropped.

- [ ] Inbound TCP `<H02_PORT>` allowed on the host firewall.
- [ ] Inbound TCP `<H02_PORT>` allowed on the cloud firewall or security group.
- [ ] Reached from **outside** this network (not from this server, not from the LAN).

Commands for the operator to approve. **NOT RUN.** Pick the one that matches your
firewall; do not run both.

```bash
# ufw (Debian/Ubuntu)
sudo ufw allow <H02_PORT>/tcp
sudo ufw status verbose

# firewalld (RHEL-family)
sudo firewall-cmd --permanent --add-port=<H02_PORT>/tcp
sudo firewall-cmd --reload
sudo firewall-cmd --list-ports
```

Outside-in test. `--server` from `connect-tracker.py` only tests from here, so use the
public port checker from a different network, such as a phone on mobile data:

```
https://www.traccar.org/port-check/
```

- [ ] The port checker reports the H02 port **open** against the public IPv4 (§5).

---

## 3. IMEI match

The device record's `uniqueId` must be **exactly** the identifier the tracker sends in
its packets. For these units that is the IMEI, and a mismatch is the most common reason
a tracker reaches the server and shows nothing: Traccar logs `Unknown device - <id>` and
stores no positions.

- [ ] The IMEI on the unit's label matches the IMEI you type into `--imei`.
- [ ] After the first packet, the identifier in `Unknown device - …` (if any) matches
      `--imei`. If it does not, the unit is not the one you registered, or the label is
      wrong. Read it again before doing anything.
- [ ] You have **not** used `--adopt-seen-id` unless you have confirmed that the
      identifier the server saw is this unit's own IMEI. Adopting another vehicle's
      identifier silently breaks that vehicle's tracking.

The identifier the server saw can be read from the log (read-only):

```bash
docker compose logs --tail 300 traccar | grep -E "Unknown device|h02"
```

Lines containing `Unknown device` name the identifier. Lines containing `*HQ,` are H02
traffic. Match the number against the label, not against the tool's suggestion.

---

## 4. APN

The APN is the carrier's, not a guess. A wrong APN produces the same symptom as dead
hardware, because the unit has no screen.

- [ ] The APN comes from the SIM provider's documentation or the SIM's paperwork.
- [ ] The SIM has data enabled, no PIN, and is not out of data or roaming into a
      surcharge. Test it in a phone first.
- [ ] `8030000 <apn>` was sent first, and the tracker replied `SET OK`.
- [ ] `RCONF` was sent afterwards, and the reply shows **MODE:GPRS**, the APN you
      intended, and the IP:port you intended. Silence is not success.

The SMS text is printed, not sent, by:

```bash
./scripts/connect-tracker.py --imei <IMEI> --name <PLATE> --server <PUBLIC_IPV4> --apn <APN> --print-sms
```

Send each line by hand, in order, from a phone, waiting for the reply each time.

---

## 5. Server address: public IPv4

The ST-906L is configured with an **IP address**, not a hostname: `8040000` takes an
IPv4 address, and a hostname is not documented for this model.

- [ ] The server's **public IPv4** is what is configured (`8040000 <IPv4> <port>`).
- [ ] The address is static, or you have accepted that a change will silently stop the
      fleet.
- [ ] The address you configured matches the address the port checker tested (§2).

To see the public IPv4 the server actually uses (read-only; this makes an outbound
request, so run it only on the server you intend to use):

```bash
curl -4 -s https://ifconfig.me; echo
```

---

## 6. Reporting interval

Two intervals matter, and both are set by SMS:

| Command | Meaning | Floor |
|---|---|---|
| `8050000 <seconds>` | Ignition on | 10 s |
| `8090000 <seconds>` | Ignition off (parked) | 10 s |

The tool refuses anything below 10 s. `0` closes GPRS entirely, which reads on the
server as a dead tracker.

- [ ] Ignition-on interval set (tool default 20 s) and read back with `RCONF`.
- [ ] Ignition-off interval set (tool default 300 s) and read back with `RCONF`.
- [ ] Measured: ten consecutive positions while moving are spaced at the intended
      interval, within a few seconds.

To measure the spacing, read the positions from the API (see §9) and compare their
`fixTime` values.

---

## 7. ACC / ignition

The unit reads ignition from the ACC wire. Constant power must come from a constant,
fused feed, **not** from ACC. The unit has no internal battery, so ACC-only wiring makes
it silent every night and loses its buffer on a power cut (`docs/TRACKER-SETUP.md`).

- [ ] Constant feed is fused and not switched by the ignition.
- [ ] ACC is wired to an ignition-switched wire and nothing else.
- [ ] Toggling ACC changes the `ignition` attribute on the next position.
- [ ] With ignition off, the unit keeps reporting at the parked interval (§6), not
      stopping.

The `ignition` attribute can be read from a position in the API (§9).

---

## 8. Commands for the operator to approve

**Every command in this section is NOT RUN.** Read each one, substitute your own values,
and run it yourself. Replace the placeholders; do not paste real IMEIs or plates into
this repository.

```bash
# (1) Server side only. Read-only. Exit 0 = mapping verified; exit 1 = not verified.
./scripts/connect-tracker.py --check

# (2) Print the SMS to send by hand. Sends nothing.
./scripts/connect-tracker.py --imei <IMEI> --name <PLATE> \
    --server <PUBLIC_IPV4> --apn <APN> --print-sms

# (3) Create the device record and wait for the tracker. Writes ONE device record to
#     Traccar. Re-running finds the same record by IMEI; it does not create another.
./scripts/connect-tracker.py --imei <IMEI> --name <PLATE> \
    --server <PUBLIC_IPV4> --apn <APN> --timeout 900

# (4) Only if the record already exists and you want to watch it. Creates nothing.
./scripts/connect-tracker.py --imei <IMEI> --watch-only --timeout 900

# (5) ONLY after §3 confirms the identifier the server saw is this unit's IMEI.
#     Changes the uniqueId of the existing record. Requires --imei and --name.
./scripts/connect-tracker.py --imei <IMEI> --name <PLATE> --adopt-seen-id <SEEN_IDENTIFIER>

# (6) Read-only logs.
docker compose logs --tail 300 traccar | grep -E "Unknown device|h02|HEX|TEXT"
```

The tool's own exit codes: **0** all five checks pass; **1** a check failed, or
`--check` could not verify the mapping; **2** bad usage, such as a missing `--imei`
or `--name`.

Do not run a `docker compose` restart, a firewall change, or an SMS as part of
acceptance. If a step needs one of them, stop and record the reason here first.

---

## 9. The five checks, and what each one means

`--timeout` applies to the whole watch. The tool reports each check on its own line
with a fault and a next action, so you know which thing to fix:

| Check | Passes when | If it fails, the likely fault |
|---|---|---|
| **a. registered** | The device record exists in Traccar | No record for this IMEI. Run without `--watch-only`, or check `--imei` against the label. |
| **b. received** | Packets from this IMEI reached the server, from the log or from `lastUpdate` | No packet from any device: SIM data, APN, server address and port, or the public firewall. An `Unknown device` line: the identifier does not match `uniqueId` (§3). An unreadable log: unknown, so read the log directly. |
| **c. fix** | A valid fix (flag `A`) on the H02 packets, or `valid: true` in the API | Flag `V`: no GPS fix, so put the antenna in clear sky and wait up to 15 min. Heartbeats only: no position packet yet, so check the reporting interval. |
| **d. fresh** | The newest stored position is at most 15 minutes old | No position since the run started. Or the newest is older: the unit has stopped reporting, so check ignition, power and the parked interval. |
| **e. plausible** | Coordinates in range, not 0,0, not in the future, not more than 24 h old | A clock or date is wrong on the tracker or the server, or the packet was misread. |

The API read-back used in §4–§7 and §10 (run from a shell where `ADMIN_EMAIL` and
`ADMIN_PASSWORD` are exported; the values are not printed):

```bash
BASE="http://127.0.0.1:${TRACCAR_WEB_PORT:-8082}"
curl -s -c /tmp/traccar-acceptance.cookie -d "email=$ADMIN_EMAIL" -d "password=$ADMIN_PASSWORD" \
     "$BASE/api/session" > /dev/null
curl -s -b /tmp/traccar-acceptance.cookie "$BASE/api/devices?uniqueId=<IMEI>"
curl -s -b /tmp/traccar-acceptance.cookie \
     "$BASE/api/positions?deviceId=<ID>&from=<UTC_START>&to=<UTC_END>"
rm -f /tmp/traccar-acceptance.cookie
```

`<UTC_START>` and `<UTC_END>` are ISO-8601 UTC, for example `2026-10-28T09:00:00Z`.
Note that `-d "password=$ADMIN_PASSWORD"` places the value on the command line, which
other local users can see in `ps` for a moment; run it on a machine you control.

---

## 10. Vehicle acceptance, after the server path passes

Only once all five checks in §9 have passed on the bench. Each row needs a written
result. A tick that nobody wrote down is not evidence.

| # | Test | How | Expected | Result |
|---|---|---|---|---|
| P1 | Server path (all five checks) | §8 step 3 | All five `ok` | **NOT RUN** |
| P2 | Port mapping and firewall | §1, §2 | Public port checker reports open | **NOT RUN** |
| P3 | IMEI match | §3 | No `Unknown device` for this unit | **NOT RUN** |
| P4 | APN and RCONF | §4 | RCONF shows MODE:GPRS, APN, IP:port | **NOT RUN** |
| P5 | Public IPv4 | §5 | Configured address = tested address | **NOT RUN** |
| P6 | Reporting interval | §6 | Ten positions spaced at the set interval | **NOT RUN** |
| P7 | ACC / ignition | §7 | `ignition` attribute follows the switch | **NOT RUN** |
| P8 | Movement | Drive a short loop | Fresh positions while moving, speed plausible | **NOT RUN** |
| P9 | Route history | Read positions for the drive (§9) | Continuous route, no long straight jumps | **NOT RUN** |
| P10 | Reconnection | Remove the antenna or disable data for 10 min, then restore | Check d recovers without a reboot | **NOT RUN** |

Operator sign-off (fill in by hand, after doing the steps yourself):

```
Unit label IMEI:     (kept in your spreadsheet, not here)
Date:                ____________
Operator:            ____________
Result of P1–P10:    ____________
Known limitations:   ____________
```

---

## 11. Known limitations of this checklist

- The tool cannot see the radio link, the SIM's signal, the antenna's position, or the
  GNSS hardware. Check **c** reads the *flag* the unit reports, which is only as good as
  the unit's own fix.
- `--check` cannot see the public path. Only the outside port test in §2 does that.
- The log-based checks depend on Traccar's log containing H02 traffic lines. If the
  unit's traffic is logged only as HEX, check **c** cannot read the fix flag from the
  log, and the API's `valid` field is the only evidence.
- The 15-minute freshness limit assumes the default parked interval (300 s). A longer
  interval needs a longer limit.
