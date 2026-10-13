#!/usr/bin/env python3
"""
Seed a demonstration fleet through the REAL H02 protocol.

Why this exists
---------------
The register of unimplemented work says, correctly, that no physical tracker has
ever connected to port 5013. That cannot be fixed without buying one. What *can*
be fixed is the second-order problem: with no tracker and no way to inject
positions, the dashboard cannot be exercised, demonstrated to a client, or
regression-tested at all. An empty deployment looks like broken software.

So this speaks H02 — the protocol the SinoTrack ST-906L will speak — over the
same TCP port the real device will use, and lets Traccar's own `h02` decoder
parse it. Positions arrive through the production code path, not around it.

What this proves, and what it does not
--------------------------------------
Proves: the protocol listener, Traccar's h02 decoding, device registration,
position storage, and everything downstream of a stored position.

Does NOT prove: the radio link, the SIM/APN setup, GNSS reception, the device's
own firmware quirks, ACC wiring, or the SMS provisioning commands. Those need the
device. `docs/UNIMPLEMENTED.md` still lists the physical test as not run, and this
script does not change that.

Usage
-----
    ./scripts/simulate-fleet.py                      # 6 vehicles, Milan
    ./scripts/simulate-fleet.py --city rome --vehicles 4
    ./scripts/simulate-fleet.py --reset              # clear seeded history first
    ./scripts/simulate-fleet.py --live --live-minutes 5   # replay in real time

Reads .env for ADMIN_EMAIL / ADMIN_PASSWORD / H02_PORT / TRACCAR_WEB_PORT, with
real environment variables winning — the same convention as the shell scripts, so
it also works under Dokploy where there is no .env.
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.cookiejar
import json
import math
import os
import random
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# ---------------------------------------------------------------------------
# H02 wire format
# ---------------------------------------------------------------------------
#
#   *HQ,<imei>,V1,<hhmmss>,<A|V>,<ddmm.mmmm>,<N|S>,<dddmm.mmmm>,<E|W>,
#       <speed>,<course>,<ddmmyy>,<status:8 hex>#
#
# Traccar's H02ProtocolDecoder matches this shape and replies
#   *HQ,<imei>,V4,V1,<yyyyMMddHHmmss>#
# so a reply containing V4/V1 is proof the packet was understood, not merely
# received. That is why this script prints the reply.
#
# Status is a bit field. The bits this script sets:
#   bit 0  vibration alarm   -> 1 (no alarm)
#   bit 1  SOS               -> 1 (no SOS)
#   bit 2  overspeed         -> 1 (no overspeed)
#   bit 10 ignition          -> 0 or 1, per position
#   bit 18 SOS (second flag) -> 1
#   bit 19 power cut         -> 1 (powered)
#
# Leaving an alarm bit at 0 raises a real alarm event in Traccar, which would
# flood the dashboard's alert feed with phantom alarms during a demo.
STATUS_BASE = 0xFFFFF9FF
IGNITION_BIT = 10


def h02_status(moving: bool) -> str:
    value = STATUS_BASE | ((1 << IGNITION_BIT) if moving else 0)
    return "%08X" % value


def h02_coord(degrees: float, is_longitude: bool) -> str:
    """Decimal degrees -> the fixed-width ddmm.mmmm / dddmm.mmmm H02 expects.

    Fixed width matters: the decoder splits on position, so 9.19 must be written
    '00911.4000', not '911.4'. Rounding is to 4 decimal places of minutes, which
    is about 0.2 m — far finer than a GNSS fix.
    """
    magnitude = abs(degrees)
    whole = int(magnitude)
    minutes = (magnitude - whole) * 60.0
    width = 3 if is_longitude else 2
    return "%0*d%07.4f" % (width, whole, minutes)


def h02_position(
    imei: str,
    when: dt.datetime,
    latitude: float,
    longitude: float,
    speed_knots: float,
    course: float,
    moving: bool,
) -> bytes:
    # The validity flag is always 'A'. A simulator with no antenna cannot have a
    # fix quality, and emitting 'V' would create invalid positions that Traccar
    # stores but the dashboard correctly refuses to draw — a confusing demo.
    # The physical test in docs/TESTING.md is what checks 'V' handling.
    sentence = "*HQ,%s,V1,%s,%s,%s,%s,%s,%s,%.2f,%03d,%s,%s#" % (
        imei,
        when.strftime("%H%M%S"),
        "A",
        h02_coord(latitude, False),
        "N" if latitude >= 0 else "S",
        h02_coord(longitude, True),
        "E" if longitude >= 0 else "W",
        speed_knots,
        int(course) % 360,
        when.strftime("%d%m%y"),
        h02_status(moving),
    )
    return sentence.encode("ascii")


# ---------------------------------------------------------------------------
# Demo geography
# ---------------------------------------------------------------------------
#
# Waypoints follow real arterials so a trail looks like a route rather than a
# scribble. (lat, lon, dwell_minutes) — the dwell is time spent on site, which is
# what produces stops and geofence arrivals in the reports.

CITIES = {
    "milan": {
        "name": "Milano",
        "vehicles": ["CAM-01", "CAM-02", "CAM-03", "CAM-04", "CAM-05", "CAM-06"],
        "imeis": [f"86123456789012{i}" for i in range(1, 7)],
        "route": [
            (45.4642, 9.1900, 6), (45.4690, 9.1870, 4), (45.4742, 9.1875, 5),
            (45.4790, 9.1858, 3), (45.4845, 9.1880, 6), (45.4878, 9.1925, 4),
            (45.4850, 9.1990, 5), (45.4795, 9.2040, 4), (45.4740, 9.2065, 5),
            (45.4690, 9.2035, 3), (45.4645, 9.1985, 5), (45.4600, 9.1940, 4),
            (45.4562, 9.1895, 6), (45.4520, 9.1855, 4), (45.4480, 9.1810, 5),
        ],
        "sites": [
            ("Deposito Nord", 45.4878, 9.1925, 400),
            ("Cliente Porta Nuova", 45.4820, 9.1950, 300),
            ("Cliente Centro", 45.4642, 9.1900, 350),
            ("Cliente Navigli", 45.4520, 9.1855, 300),
        ],
    },
    "rome": {
        "name": "Roma",
        "vehicles": ["CAM-01", "CAM-02", "CAM-03", "CAM-04"],
        "imeis": [f"86123456789013{i}" for i in range(1, 5)],
        "route": [
            (41.9028, 12.4964, 6), (41.9080, 12.4930, 4), (41.9135, 12.4918, 5),
            (41.9180, 12.4890, 4), (41.9230, 12.4865, 5), (41.9280, 12.4880, 4),
            (41.9310, 12.4930, 5), (41.9270, 12.4990, 4), (41.9210, 12.5010, 5),
            (41.9150, 12.5005, 4), (41.9090, 12.4990, 3), (41.9040, 12.5030, 5),
        ],
        "sites": [
            ("Deposito Tiburtina", 41.9135, 12.4918, 400),
            ("Cliente Termini", 41.9009, 12.5018, 300),
            ("Cliente Prati", 41.9140, 12.4910, 300),
        ],
    },
}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres.

    Deliberately the same formula Traccar uses to turn a trail into `distance`,
    so what this script generates and what the reports measure agree.
    """
    radius = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    a = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(a))


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing in degrees, for the course field."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta = math.radians(lon2 - lon1)
    y = math.sin(delta) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(delta)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def build_cycle(
    route,
    step_minutes: float = 1.0,
    speed_kmh=(24.0, 34.0),
    jitter: float = 1.2e-5,
):
    """One lap of the route as a time-ordered fix list.

    Returns ``(fixes, lap_minutes)``, where each fix is
    ``(minutes_into_lap, latitude, longitude, speed_kmh, stopped)``.

    The vehicle stands still at each waypoint for that site's dwell time, then
    drives the leg to the next waypoint at a steady speed, one fix per
    ``step_minutes``. That relationship is the whole point: because a leg is
    interpolated at constant speed, the distance between two consecutive fixes
    agrees with the speed the packet reports. Traccar derives trips, stops and
    distance from exactly that agreement. A trail that jumps 80 m every six
    minutes while claiming 28 km/h has no coherent speed to derive anything from
    — no trips, no stops, no distance — however long you wait for it. An earlier
    version of this function walked a distance-indexed polyline at evenly spaced
    *samples* rather than by time and produced precisely that.
    """
    fixes = []
    clock = 0.0
    count = len(route)
    for index, (lat, lon, dwell) in enumerate(route):
        # Arrive, then stand still. Every dwell fix shares one exact coordinate so
        # the recorded distance across the stop is zero and Traccar reads it as a
        # genuine stop rather than a slow crawl.
        for _ in range(max(1, int(round(dwell / step_minutes)))):
            fixes.append((clock, lat, lon, 0.0, True))
            clock += step_minutes

        next_lat, next_lon, _ = route[(index + 1) % count]
        leg_metres = haversine_m(lat, lon, next_lat, next_lon)
        if leg_metres <= 0:
            continue
        cruise = random.uniform(*speed_kmh)
        leg_minutes = leg_metres / (cruise * 1000.0 / 60.0)
        steps = max(1, int(round(leg_minutes / step_minutes)))
        for step in range(1, steps + 1):
            fraction = step / steps
            fixes.append(
                (
                    clock + leg_minutes * fraction,
                    lat + (next_lat - lat) * fraction + random.uniform(-jitter, jitter),
                    lon + (next_lon - lon) * fraction + random.uniform(-jitter, jitter),
                    cruise,
                    False,
                )
            )
        clock += leg_minutes
    return fixes, clock


def trail_slice(fixes, lap_minutes: float, minutes: float, start_minutes: float):
    """The fixes covering ``minutes`` of driving that begin ``start_minutes`` into the lap.

    Wraps around the loop as many times as the window needs, so a short route can
    still fill a long demonstration trail.
    """
    out = []
    base = 0.0
    for _ in range(int(minutes // lap_minutes) + 2):
        for offset, lat, lon, speed, stopped in fixes:
            when = base + offset
            if when < start_minutes:
                continue
            if when > start_minutes + minutes:
                return out
            out.append((when - start_minutes, lat, lon, speed, stopped))
        base += lap_minutes
    return out


# ---------------------------------------------------------------------------
# Traccar API (JSESSIONID cookie, form-encoded login)
# ---------------------------------------------------------------------------

_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)


class Api:
    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")

    def login(self, email: str, password: str) -> dict:
        data = urllib.parse.urlencode({"email": email, "password": password}).encode()
        request = urllib.request.Request(f"{self.base}/api/session", data=data)
        try:
            with _OPENER.open(request, timeout=20) as response:
                user = json.load(response)
        except urllib.error.HTTPError as exc:
            raise SystemExit(
                f"login failed for {email}: HTTP {exc.code}. "
                "Check ADMIN_EMAIL / ADMIN_PASSWORD in .env."
            )
        if not user.get("id"):
            raise SystemExit(f"login failed: {user}")
        return user

    def call(self, path: str, method: str = "GET", body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(f"{self.base}/api{path}", data=data, method=method)
        if data:
            request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        try:
            with _OPENER.open(request, timeout=25) as response:
                raw = response.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            return {"_error": exc.code, "_body": exc.read().decode(errors="replace")[:300]}


# ---------------------------------------------------------------------------
# .env loading (real environment wins, exactly like scripts/backup.sh)
# ---------------------------------------------------------------------------

def load_env(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


# ---------------------------------------------------------------------------
# Seeding
# ---------------------------------------------------------------------------

def replay(
    imei: str,
    fixes,
    host: str,
    port: int,
    step_minutes: float,
    live: bool,
    pace_ms: float = 10.0,
) -> tuple[int, str, float]:
    """Send one vehicle's trail.

    Returns ``(count, first reply, trail_minutes)``. The first reply is proof the
    decoder understood the packet, not merely that it was received.
    """
    if not fixes:
        return 0, "(nothing to send)", 0.0

    trail_minutes = fixes[-1][0]
    end_time = dt.datetime.now() - dt.timedelta(minutes=1)
    start_time = end_time - dt.timedelta(minutes=trail_minutes)

    sent = 0
    reply = None
    previous = None
    with socket.create_connection((host, port), timeout=20) as connection:
        for relative, latitude, longitude, speed_kmh, stopped in fixes:
            when = start_time + dt.timedelta(minutes=relative)

            course = bearing(previous[0], previous[1], latitude, longitude) if previous else 0.0
            # H02 carries speed in knots.
            speed_knots = 0.0 if stopped else speed_kmh / 1.852
            packet = h02_position(
                imei, when, latitude, longitude, speed_knots, course, not stopped
            )
            connection.sendall(packet)
            if reply is None:
                connection.settimeout(4)
                try:
                    reply = connection.recv(4096).decode("ascii", "replace").strip()
                except socket.timeout:
                    reply = "(no reply)"
            previous = (latitude, longitude)
            sent += 1

            if live:
                # A live replay means a fix per step in real time, not sooner.
                time.sleep(step_minutes * 60.0)
            elif pace_ms:
                # One packet at a time, with a gap between them.
                #
                # Blasting the whole trail into the socket at once looks
                # harmless and is not. Traccar reads a burst in chunks, and the
                # remainder is still queued when the client closes — so it is
                # discarded, silently, with nothing in the log to say why.
                # Measured against Traccar 6.16: 60 packets in a single burst
                # stored 24; the identical 60 with a 20 ms gap stored all 60.
                # A trail is 176 fixes, so this is the difference between a
                # demonstration and a quarter of one.
                time.sleep(pace_ms / 1000.0)

        if not live:
            # Let the server finish reading before the socket is torn down.
            time.sleep(0.25)

    return sent, reply or "(no reply)", trail_minutes


def main() -> int:
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_env(os.path.join(here, ".env"))

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    parser.add_argument("--city", default="milan", choices=sorted(CITIES))
    parser.add_argument("--vehicles", type=int, default=0, help="0 = all of the city's list")
    parser.add_argument("--host", default=os.environ.get("H02_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("H02_PORT", "5013")))
    parser.add_argument(
        "--api",
        default=os.environ.get("SIMULATOR_API")
        or "http://127.0.0.1:%s" % os.environ.get("TRACCAR_WEB_PORT", "8082"),
    )
    parser.add_argument("--email", default=os.environ.get("ADMIN_EMAIL", ""))
    parser.add_argument("--password", default=os.environ.get("ADMIN_PASSWORD", ""))
    parser.add_argument("--step", type=float, default=1.0, help="minutes between fixes")
    parser.add_argument(
        "--window",
        type=int,
        default=180,
        help="minutes of history to synthesise. Stays close to 'now' on purpose: "
        "Traccar discards positions that arrive far out of order.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="delete each vehicle's stored positions first. Without it a second "
        "run appends a second trail on top of the first, and every report then "
        "sums both.",
    )
    parser.add_argument("--live", action="store_true", help="replay in real time")
    parser.add_argument("--live-minutes", type=int, default=5)
    parser.add_argument(
        "--pace-ms",
        type=float,
        default=10.0,
        help="gap between packets. Do not set this to 0: Traccar discards the "
        "tail of a burst. See replay().",
    )
    args = parser.parse_args()

    if not args.email or not args.password:
        raise SystemExit(
            "ADMIN_EMAIL and ADMIN_PASSWORD are required. Set them in .env or pass "
            "--email/--password."
        )

    city = CITIES[args.city]
    names = city["vehicles"][: args.vehicles] if args.vehicles else city["vehicles"]
    imeis = city["imeis"][: len(names)]

    print()
    print("  Seeding %d vehicle(s) into %s via H02 on %s:%s" % (len(names), city["name"], args.host, args.port))
    print("  API: %s" % args.api)
    print()

    api = Api(args.api)
    api.login(args.email, args.password)
    print("  authenticated as %s" % args.email)

    # Geofences. Matched by name first — Traccar does not enforce unique geofence
    # names, so creating without looking would append duplicates on every run.
    existing_sites = {g.get("name"): g for g in api.call("/geofences?limit=1000") or []}
    for name, latitude, longitude, radius in city["sites"]:
        if name in existing_sites:
            continue
        # NOTE: Traccar geofence area is WKT with LATITUDE FIRST. Swapping these is
        # the single most common integration bug with this API.
        result = api.call(
            "/geofences",
            "POST",
            {
                "name": name,
                "area": "CIRCLE (%f %f, %d)" % (latitude, longitude, radius),
                "attributes": {"color": "#22d3ee", "hidden": "false"},
            },
        )
        print("    + site %s" % name if "_error" not in result else "    ! %s -> %s" % (name, result))

    # Devices. Matched by uniqueId, which Traccar does enforce — a second run that
    # POSTed blindly would fail with a SQL constraint violation and look broken.
    existing_devices = {d.get("uniqueId"): d for d in api.call("/devices?limit=1000") or []}
    for name, imei in zip(names, imeis):
        if imei in existing_devices:
            continue
        result = api.call(
            "/devices",
            "POST",
            {
                "name": name,
                "uniqueId": imei,
                "disabled": False,
                "attributes": {"model": "st-906l", "deviceType": "truck"},
            },
        )
        print("    + vehicle %s (%s)" % (name, imei) if "_error" not in result else "    ! %s -> %s" % (name, result))

    # Spread the vehicles along the loop, each starting at a different point, so a
    # fresh deployment shows several vehicles in different places rather than a
    # convoy nose to tail.
    fixes, lap_minutes = build_cycle(city["route"], args.step)
    window = args.live_minutes if args.live else args.window

    if args.reset:
        current = {d.get("uniqueId"): d for d in api.call("/devices?limit=1000") or []}
        for name, imei in zip(names, imeis):
            device = current.get(imei)
            if not device:
                continue
            result = api.call(
                "/positions?deviceId=%s&from=2000-01-01T00:00:00Z&to=2100-01-01T00:00:00Z"
                % device["id"],
                "DELETE",
            )
            if "_error" in result:
                print("    ! %s -> %s" % (name, result))
            else:
                print("    - %s: history cleared" % name)

    total_sent = 0
    total_km = 0.0
    print()
    for index, (name, imei) in enumerate(zip(names, imeis)):
        start_minutes = (index / len(names)) * lap_minutes
        vehicle_trail = trail_slice(fixes, lap_minutes, window, start_minutes)
        km = sum(
            haversine_m(a[1], a[2], b[1], b[2])
            for a, b in zip(vehicle_trail, vehicle_trail[1:])
        ) / 1000.0
        count, reply, trail_minutes = replay(
            imei,
            vehicle_trail,
            args.host,
            args.port,
            args.step,
            args.live,
            args.pace_ms,
        )
        total_sent += count
        total_km += km
        print(
            "    > %-8s %3d fixes over %3.0f min, %5.1f km, from lap %3.0f min  reply=%s"
            % (name, count, trail_minutes, km, start_minutes, reply)
        )

    print()
    print(
        "  %d positions sent through the H02 decoder, %.1f km of driving."
        % (total_sent, total_km)
    )
    print("  Open the dashboard and sign in. Nothing here proves the physical")
    print("  tracker works — see docs/UNIMPLEMENTED.md.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
