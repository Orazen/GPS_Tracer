# Hardware acceptance testing

**Tracker #1 must pass everything here before tracker #2 is bought.** A tracker
that works on the bench and fails in a truck costs a day and a visit.

Record the result of every line. A tick that nobody wrote down is not evidence.

---

## A. Bench tests

Tracker on a bench supply, ACC on a switch, dashboard open, and the server log
tailing in a second window:

```bash
docker compose -f docker-compose.yml logs -f traccar
```

| # | Test | How | Expected | Result |
|---|---|---|---|---|
| A1 | 4G attaches | Power on, watch the status LED | LED pattern means registered on network | |
| A2 | GPS fix | Outdoors or by a window | Fix within ~1 min, position roughly right | |
| A3 | Server connection | `nc -vz <server> 5013` from the tracker network | Connected | |
| A4 | Live position | Watch the dashboard | Marker appears and moves with the tracker | |
| A5 | Reporting interval | Time 10 updates | Matches the configured interval | |
| A6 | Speed | Carry it at a brisk walk | Plausible; not zero, not 2000 km/h | |
| A7 | Timestamps | Compare the dashboard clock with real time | Within a couple of minutes | |
| A8 | Ignition / ACC | Toggle ACC | Ignition state follows the switch | |
| A9 | Vehicle power removed | Pull the constant feed | Behaviour as documented — see `ST-906L.md` | |
| A10 | Backup battery | Disconnect everything | If it has one, it keeps reporting | |
| A11 | SOS | Trigger it, if the unit has one | Alarm reaches the dashboard | |
| A12 | Network loss | Remove the antenna or disable the SIM | Stops reporting, then recovers | |
| A13 | Reconnection | Restore the network | Reconnects on its own, no reboot | |
| A14 | Buffered positions | Offline for 10 min while moving, then reconnect | Offline positions replayed, or the gap documented | |
| A15 | Wrong-identifier handling | Change the identifier | Traccar does not crash or accept garbage | |

### A6 deserves a second look

Screens report speed in km/h but some devices send knots. A tracker showing a
constant "0 km/h" while moving usually means the device type in Traccar is wrong,
not that the tracker is broken. Check **Settings → Devices → Type** before
suspecting the hardware.

---

## B. Road tests

With the tracker installed in the vehicle.

| # | Test | How | Expected | Result |
|---|---|---|---|---|
| B1 | Live movement | Drive | Marker follows the vehicle within a few seconds | |
| B2 | Route history | Drive a loop | Full route reconstructed, no straight lines across the map | |
| B3 | Route playback | Replay the loop | Ordered, correctly timed, speeds plausible | |
| B4 | Trip detection | Drive, then stop 10+ min | One trip; a stop entry appears | |
| B5 | Stop detection | Park at a customer site | Stop recorded, correct duration, an address if geocoded | |
| B6 | Speed report | Drive at a steady speed | Report matches the speedometer within ~10% | |
| B7 | Geofence entry | Drive into a customer zone | Entry event fires | |
| B8 | Geofence exit | Drive out | Exit event fires | |
| B9 | Overspeed | Exceed the configured limit | Alert fires and is not duplicated | |
| B10 | Tracker offline | Pull the power | Offline alert within the expected window | |
| B11 | Tracker reconnect | Restore power | Back online, no reboot needed | |
| B12 | Ignition off, parked | Park with ignition off | Reporting continues if constant power is wired | |
| B13 | Signal quality in a valley/urban canyon | Drive somewhere hostile | Fix degrades but recovers; no permanent loss | |
| B14 | Overnight | Leave it parked overnight | Reconnects in the morning; buffered positions replay | |

---

## C. Verifying the link tables

Traccar only generates geofence enter/exit events for zones linked to the device
or its group. This is a common and quiet failure: everything looks configured, and
no arrival is ever recorded.

```sql
-- in the database container
SELECT deviceid, geofenceid FROM tc_device_geofence;
SELECT geofenceid, COUNT(*) FROM tc_positions
  WHERE geofenceids IS NOT NULL GROUP BY geofenceid;
```

If the first query returns nothing for your device, geofence events will never
fire for it.

Note that the REST API in Traccar 6.16 **cannot** create these links — see
[`ARCHITECTURE.md`](ARCHITECTURE.md) — so set them in the Traccar web UI, and run
the queries above to confirm.

---

## D. Operations rehearsal

The failure modes that actually hurt are operational, not electrical.

| # | Test | Expected | Result |
|---|---|---|---|
| D1 | `./scripts/backup.sh` | A non-trivial dump appears | |
| D2 | `./scripts/backup.sh restore <file>` | Data returns, Traccar restarts | |
| D3 | `docker compose down && up -d` | Everything comes back, data intact | |
| D4 | `docker compose restart` | Clean restart, no manual repair | |
| D5 | Reboot the host | Stack comes back unattended | |
| D6 | A second person can log in | Roles behave as intended | |
| D7 | You can find your way back | Docs suffice without you | |

---

## E. Sign-off

Only proceed to order more trackers when all of the following hold:

- [ ] Every bench test passed or is documented as a known limitation
- [ ] Every road test passed
- [ ] Geofence links verified (section C)
- [ ] A backup and a restore both completed successfully
- [ ] The unknown list in `ST-906L.md` is resolved or explicitly accepted
- [ ] Known limitations are written down and shared with the client

Then keep the tracker you tested as the reference unit for everything that
follows.
