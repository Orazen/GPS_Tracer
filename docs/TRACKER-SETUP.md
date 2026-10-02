# Tracker setup

Wiring, SIM, and per-tracker provisioning. For device specifics see
[`ST-906L.md`](ST-906L.md); for acceptance see [`TESTING.md`](TESTING.md).

---

## Principle

**Bring one tracker up on a bench before fitting it to a truck.** Fitting an
unproven unit and then debugging it in a vehicle costs hours. On a bench you can
touch every wire, watch the logs, and pull the power in an instant.

---

## 1. Bench setup

- the tracker
- a 12 V bench supply, or a spare battery
- a switch to simulate the ACC/ignition input
- the server's public hostname and port `5013`
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

Order matters. **APN first**, then the server, then TCP-only mode.

SinoTrack documents two syntaxes; either is fine, but be consistent.

### Comma form (recommended - clearer, and includes the TCP-only fix)

```text
apn,your_carrier_apn#
server,0,your-server.com,5013,0#
mode,1#
```

### Numeric form (vendor activation sequence)

```text
8030000 your_carrier_apn
8040000 <your-server-ip> 5013
7100000
```

`server,0,...` accepts a hostname; `8040000 ...` takes an IP. If you use the IP
form, it must be your **public** address.

> **`mode,1#` is not optional in practice.** Some H02 firmware mixes UDP and TCP
> on one connection; the UDP keep-alives then look like garbage on Traccar's
> TCP-only listener and the device appears connected but never delivers a
> position. Send it.

Optionally set the timezone so timestamps are sane:

```text
896<password> 00
```

Do **not** commit these strings to Git. They are firmware-specific, and the
per-unit password is a secret.

---

## 4. Create the device in Traccar

Either let the tracker check in and appear under **Settings -> Devices**, or
pre-create it: **Settings -> Devices -> Add Device**.

Set:

- **Identifier** - the IMEI (from the tracker label)
- **Name** - the vehicle registration plate, e.g. `AB123CD`
- **Type** - *Vehicle* or *Tracker*. Set this properly: Traccar uses it to
  interpret computed values, and a wrong type produces misleading speeds and
  distances. A tracker that reads "0 km/h" while moving is usually this.
- **Reporting interval** - slightly longer than the tracker's own interval, so
  you do not get an offline alert every time a report is a few seconds late.

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
> ACC it is silent whenever the vehicle is parked with the ignition off - most of
> the night - and it cannot buffer positions across a power loss. ACC is an
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

Keep this in a spreadsheet or the same password manager as the credentials -
**not** in this repository. An IMEI identifies a SIM, and the vehicle
registration is personal data tied to an employee.

---

## 7. Confirm before leaving the bench

On the dashboard:

- a live position that moves when you move the tracker
- the `A` flag on the H02 packet, not `V` (invalid fix)
- the correct vehicle name
- a plausible, non-zero speed
- ignition state following the ACC switch
- a sensible "last update" interval
- **no garbled bytes in the Traccar log** - if there are some, resend `mode,1#`
- no repeated errors

Then work through [`TESTING.md`](TESTING.md) before installing in a truck.
