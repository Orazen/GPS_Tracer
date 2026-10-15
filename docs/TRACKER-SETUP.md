# Tracker setup

Wiring, SIM, and per-tracker provisioning. For device specifics see
[`ST-906L.md`](ST-906L.md); for acceptance see [`TESTING.md`](TESTING.md).

> **If this is the first tracker you have brought up here, start with
> [`connect-hardware.html`](connect-hardware.html).** It is the same path on one
> printable page — six numbered hops, what each one fails silently on, and the
> one command that checks it. This document is the reference version behind it:
> read it before trusting the tool.

---

## Principle

**Bring one tracker up on a bench before fitting it to a truck.** Fitting an
unproven unit and then debugging it in a vehicle costs hours. On a bench you can
touch every wire, watch the logs, and pull the power in an instant.

---

## 0. The fast path

On a **fresh server**, the server side is one command. It creates the
environment file, generates both secrets, brings the stack up, creates the first
administrator, closes registration again behind them and runs the smoke test:

```bash
./scripts/setup.sh
```

Then, per tracker. **Two ways to do the same thing**, and the second needs no shell
at all:

```bash
./scripts/connect-tracker.py --check
```

or, in the dashboard, **Connect a tracker** (administrators only). It shows the same
six hops with live state for the identifier in front of you, reads back the
registration settings this server is actually running with, lists every identifier
Traccar has already refused with a one-click "register it" action, and generates
the SMS block below from your APN and server address. It exists because the
technician standing at a vehicle has a phone, not a terminal — and because "did it
connect?" should not require reading a log to answer.

```bash
./scripts/connect-tracker.py --imei 4210209006 --name AB123CD --server vps.example.com --apn internet
```

That one command:

- verifies the H02 port is published onto the port Traccar actually reads, which
  is the mistake in [`UNIMPLEMENTED.md`](UNIMPLEMENTED.md) §7.8 that let a stack
  come up healthy while decoding nothing;
- creates the device record in Traccar, so you do not have to drive its UI;
- prints the SMS sequence below with your APN and server already substituted;
- then **waits**, and tells you which of three things has happened — *registered*,
  *reached the server*, *real position* — because only the third one means it
  works; and
- when nothing arrives, reads Traccar's log and names the fault instead of leaving
  you to guess between six identical-looking ones.

Everything below is the manual version of the same thing, and the reference for
what the command is doing. Read it before trusting the command.

---

## 1. Bench setup

- the tracker
- a 12 V bench supply, or a spare battery
- a switch to simulate the ACC/ignition input
- the server's **public** hostname or IP, and port `5013`
- the Traccar dashboard open, and the server log in a second window:

  ```bash
  docker compose logs -f traccar
  ```

---

## 2. SIM - do this first

Use a **data-only M2M SIM** covering every country the trucks operate in. See
[`ST-906L.md`](ST-906L.md#sim) for the roaming-cost trap, which is the most common
way a tracker project fails quietly.

Test the SIM in a phone before putting it in the tracker. The device has no
screen, so a SIM that cannot attach is indistinguishable from dead hardware.

---

## 3. Configure the tracker

Order matters. **APN first**, then the server, then the reporting intervals, then
GPRS mode.

The device is configured entirely by SMS, so an unrecognised command is not a
harmless experiment — the unit ignores it silently and the only symptom is that
nothing ever arrives. The commands below are the ones in the ST-906L manual.

| SMS | Purpose |
|---|---|
| `8030000 <apn>` | set the APN. Add `<user> <password>` only if the carrier needs them |
| `8040000 <public-ip> <port>` | point the tracker at this server, e.g. `8040000 203.0.113.10 5013` |
| `8050000 <seconds>` | reporting interval with ignition **on** (manual default 20) |
| `8090000 <seconds>` | reporting interval with ignition **off** (manual default 300) |
| `7100000` | select GPRS mode explicitly instead of trusting the factory default |
| `RCONF` | read the settings back |

`0000` in each command is the unit's password. It is three digits of verb
(`803`) plus the four-digit password (`0000`) — if the unit's password has been
changed, replace those four digits and keep the three-digit prefix.

Two things worth knowing about the intervals:

- **The floor is 10 seconds.** Below that, and `T=0` in particular, the unit stops
  reporting over GPRS. It reads on the server as a dead tracker, not as a
  configured one.
- `8050000` is the one that matters for driving hours. `8090000` is what it does
  parked, which on a 24/7 install is most of the night; set it long enough not to
  burn the SIM's data allowance and short enough to notice a theft.

`8040000` takes an **IP** according to the manual. A hostname is reported to work
on some units but is not documented, so use the public address — and check it with
`RCONF` rather than assuming.

### Confirm the settings took

Send `RCONF`. The reply lists `MODE:GPRS`, the APN and the server IP and port. The
documented reply to a successful setting command is `SET OK`.

**Silence is not success.** This is the whole reason `RCONF` exists: with no
read-back, the only evidence that any of the above worked is a packet arriving on
the server, and that single symptom has at least six causes.

> **A note on the transcript.** An earlier revision of this document recommended
> `apn,your_carrier_apn#`, `server,0,your-server.com,5013,0#` and `mode,1#` as an
> equivalent "comma form". Those belong to other tracker command families and are
> **not in the ST-906L manual**. They have been removed. If you have been sending
> them, send the table above instead: the unit has been ignoring everything.
>
> `mode,1#` in particular was presented as a required fix for a UDP/TCP firmware
> bug. One third-party page makes that claim; no vendor manual and no Traccar
> transcript corroborates it. A closely related version of the claim — UDP
> keep-alives "mixed into" a TCP connection — is not how the two transports work.
> If you see a connection that opens and then produces garbage, treat resending
> `mode,1#` as a cheap thing to try, not as a known fix.

Do **not** commit these strings to Git. They are firmware-specific, and the
per-unit password is a secret.

---

## 4. Create the device in Traccar

`./scripts/connect-tracker.py` does this for you. To do it by hand:
**Settings → Devices → Add Device**, and set:

- **Identifier** — the IMEI from the tracker label. This is `uniqueId` in the API,
  and it must match exactly what the tracker sends in its login packet.
- **Name** — the vehicle registration plate, e.g. `AB123CD`
- **Category** — *Vehicle* or *Tracker*. Set this properly: Traccar uses it to
  interpret computed values, and the wrong one produces misleading speeds and
  distances. A tracker that reads "0 km/h" while moving is usually this.
  Through the API it must be the **top-level `category` field**. Putting it only in
  `attributes.deviceType` does nothing at all — measured, and the reason
  `scripts/connect-tracker.py --category` used to have no effect (see
  [`UNIMPLEMENTED.md`](UNIMPLEMENTED.md) §7.12). Re-running the tool repairs the
  category on a device that was registered before that fix.
- **Reporting interval** — slightly longer than the tracker's own interval, so you
  do not get an offline alert every time a report is a few seconds late.

### Traccar does not auto-register unknown devices

This is the single most confusing thing about bringing a tracker up, so it is
worth stating plainly: **by default Traccar ignores a packet from an IMEI it does
not have a device for.** It logs

```text
WARN: Unknown device - 865282040015552 (5.35.166.137)
```

and stores **no position**. The tracker is working, the SIM is working, the
network is working, and the dashboard shows nothing. The identifier in that
warning is what `uniqueId` has to be.

The fix is either to create the device with that exact identifier —
`./scripts/connect-tracker.py --adopt-seen-id 865282040015552` will do it for you
— or to let the server create devices by itself:

```bash
TRACCAR_REGISTER_UNKNOWN=true
```

That makes a tracker appear the moment it first connects, with no server-side step
at all. On this stack a device created that way arrives **named after the raw
identifier** and with an **empty category**, so the switch ships with the two keys
that make the result usable:

| Setting | What it does | Default here |
|---|---|---|
| `TRACCAR_REGISTER_UNKNOWN` | create a device on an unknown identifier's first packet | `false` |
| `TRACCAR_REGISTER_UNKNOWN_CATEGORY` | the category given to the new device | `truck` |
| `TRACCAR_REGISTER_UNKNOWN_REGEX` | allow-list: only identifiers matching this pattern are created | empty — anything |

The category is not decoration. Traccar derives speed and distance from it, so a
device that appears without one reports numbers that are quietly wrong.

**The allow-list must match the whole identifier.** Traccar applies it with Java's
`String.matches`, which anchors both ends. A pattern naming a *prefix* therefore
accepts nothing — and does so silently, because the symptom is the same
`Unknown device` warning you get when the feature is off entirely. Verified on this
stack rather than remembered: the image's connection handler calls
`java/lang/String.matches(Ljava/lang/String;)Z`.

| Pattern | What it accepts |
|---|---|
| `^42102` | **nothing** — the identifier does not end there |
| `42102.*` | a unit whose IMEI starts `42102` |
| `42102.*\|42111.*` | either prefix |

Two defences against that trap, both measured working: the container warns about it
on startup whenever a pattern is set, and `./scripts/connect-tracker.py --check`
reads the rendered file back and reports the state actually in force, instead of
telling you the default story.

The trade-off is real and worth taking deliberately: the H02 port is on the public
internet, so **anything** that opens a connection and sends a plausible H02 packet
becomes a device record, and your roster fills with entries named after whatever
the packet contained. With no allow-list set, that is the whole exposure. It is the
right setting for a bench or a pilot — especially with the regex narrowed to your
own IMEI range — and the wrong one for a production fleet on a public port.

---

## 5. Wiring into a truck

| Wire | Connect to |
|---|---|
| VCC | **constant** fused positive from the battery |
| ACC | ignition-switched positive (signal only) |
| GND | chassis ground |

> **Power the tracker from a constant positive, not from ACC.**
>
> The ST-906L appears to have no internal battery. If it is powered only through
> ACC it is silent whenever the vehicle is parked with the ignition off — most of
> the night — and it cannot buffer positions across a power loss. ACC is an
> *input signal* here, never the power rail.

Confirm the exact 4-pin harness pinout with the vendor before cutting anything.

Also:

- **Fuse the constant feed** on the vehicle's auxiliary circuit. Do not tap the
  main supply.
- **Use a proper ground.** A poor ground is the most common cause of a tracker
  that works on the bench and misbehaves in a vehicle.
- **Route away from the alternator and starter**, keep the cable short and
  shielded. Charging-system noise degrades GNSS measurably.
- **Mount the antenna with a clear view of the sky.** Under the seat or in the
  roof console gives a materially worse fix than the roof. That is worth more than
  any antenna upgrade. Do not place it next to the vehicle's own GPS antenna.
- **Label the device** with its Traccar device id so a future technician can map
  tracker to vehicle without guessing.

### Leave these alone

- **Do not wire the engine-cut relay.** See
  [`ST-906L.md`](ST-906L.md#2-remote-engine-cut-off-relay).
- **Do not enable voice monitoring.** See
  [`ST-906L.md`](ST-906L.md#1-voice-monitoring-mic).

---

## 6. Per-tracker record

| Tracker IMEI | Vehicle / plate | Driver | Installed | SIM | ACC pin | Mode SMS sent |
|---|---|---|---|---|---|---|

Keep this in a spreadsheet or the same password manager as the credentials —
**not** in this repository. An IMEI identifies a SIM, and the vehicle
registration is personal data tied to an employee.
`./scripts/connect-tracker.py` prints a row for it on success.

---

## 7. Confirm before leaving the bench

On the dashboard:

- a live position that moves when you move the tracker
- the `A` flag on the H02 packet, not `V` (invalid fix)
- the correct vehicle name
- a plausible, non-zero speed
- ignition state following the ACC switch
- a sensible "last update" interval
- no repeated errors in the Traccar log

Then work through [`TESTING.md`](TESTING.md) before installing in a truck.

---

## 8. When it does not connect

Work out **which** of three states you are in before changing anything. They have
different causes and none of the fixes overlap.

| State | What it means | Where to look |
|---|---|---|
| Nothing in the log | The tracker never reached the server | Power, SIM, APN, the server address stored in the unit, the firewall, the published port |
| `Unknown device - <id>` | A packet **arrived**; Traccar read an identifier it has no device for | Create the device with that identifier, or `--adopt-seen-id`. If auto-registration is on, check `TRACCAR_REGISTER_UNKNOWN_REGEX` accepted it — the whole identifier must match |
| Traffic, but no position | The server is decoding, but there is no usable fix or no position packet | Antenna and sky view, `A` vs `V`, the protocol and port, heartbeats only |

`./scripts/connect-tracker.py --imei <imei> --watch-only` prints the same
diagnosis from the log automatically, including the identifier Traccar actually
read when it is the second row.

The things that catch people out:

- **A heartbeat is not a position.** An H02 `HTBT` keep-alive can arrive without
  ever moving Traccar's online flag. A connection in the log is not evidence of a
  working tracker; a stored position is.
- **An ignored allow-list looks exactly like a broken tracker.** If
  `TRACCAR_REGISTER_UNKNOWN_REGEX` is set and the identifier does not match it end
  to end, the packet is refused with the same warning as an unregistered device.
  `--check` prints the pattern in force.
- **A first fix can take 15 minutes**, longer indoors or under metal. Time out too
  early and a working unit looks broken.
- **The published port is the host's `H02_PORT`; the container's is always 5013.**
  An outside test from another network is the only proof of the public path:
  <https://www.traccar.org/port-check/>
- **Confirm the protocol before anything else.** An H02 packet starts with `*HQ`
  and ends with `#`. Traccar's own guide:
  <https://www.traccar.org/identify-protocol/>
- **The dashboard refuses nothing and hides nothing: if it says a hop is blocked,
  it has the evidence.** If it says a hop is *not visible from here*, that is not a
  failure and not a spinner — the server has no way to see that hop, and pretending
  otherwise would send you to the wrong end of the problem. See
  [`UNIMPLEMENTED.md`](UNIMPLEMENTED.md) §7.13.

Hop by hop, with the symptom each one produces side by side, is also on
[`connect-hardware.html`](connect-hardware.html) — worth printing for whoever is
standing at the vehicle with a phone.

---

## Sources

The command set and the port were checked against vendor and Traccar material
rather than remembered. If you are re-deriving any of this, start here:

- SinoTrack ST-906 manual — <https://www.manualslib.com/manual/3675486/Sinotrack-St-906.html>
- SinoTrack ST-906GL manual, settings commands — <https://www.manualslib.com/manual/3635014/Sinotrack-St-906gl.html?page=11>
- SinoTrack help centre — <https://www.sinotrackgps.com/help-center>
- Traccar, identify a protocol — <https://www.traccar.org/identify-protocol/>
- Traccar, troubleshooting — <https://www.traccar.org/troubleshooting/>
- Traccar, configuration reference (`database.registerUnknown`) — <https://www.traccar.org/configuration-file/>
- Traccar, TCP port checker — <https://www.traccar.org/port-check/>
