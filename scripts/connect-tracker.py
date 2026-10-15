#!/usr/bin/env python3
"""
Connect a physical tracker to this stack, in one command.

The problem this solves
-----------------------
Bringing a tracker online used to be six manual steps spread across two systems
and a phone: send four SMS, then drive Traccar's web UI to create a device, then
stare at a map wondering whether "nothing appears" means a wrong APN, a wrong
port, a firewall, an unregistered IMEI or no GPS fix. Every one of those looks
identical from the map. Section 7.8 of docs/UNIMPLEMENTED.md is the story of a
stack that passed every healthcheck while decoding nothing, found only by sending
a packet and reading the decoder's log.

So this script does the two halves and joins them:

  1. Server side.  It checks the H02 listener is actually published on the port
     Traccar reads (not merely on the port the operator typed), and it creates
     the device record, so nobody has to use Traccar's UI.
  2. Device side.  It prints the exact SMS sequence for the tracker, in the
     syntax the vendor's own manual documents, with your APN and server already
     substituted.
  3. The junction.  It then WATCHES, and reports which of three things has
     happened -- registered, reached the server, real position -- because those
     are three different states and only the third one means "it works". When
     nothing arrives it reads Traccar's log and names the actual fault, including
     the one that has a one-command fix: an IMEI the server saw but did not know.

Read the whole of `docs/TRACKER-SETUP.md` before wiring anything into a vehicle.
This gets a tracker talking to the server. It does not make the installation
safe, and it proves nothing about the radio link, the SIM or the antenna.

Usage
-----
    ./scripts/connect-tracker.py --check                        # is the listener right?
    ./scripts/connect-tracker.py --imei 4210209006 --name AB123CD --server vps.example.com
    ./scripts/connect-tracker.py --imei 4210209006 --watch-only  # already configured
    ./scripts/connect-tracker.py --imei 4210209006 --adopt-seen-id 4210209006

Reads .env for ADMIN_EMAIL / ADMIN_PASSWORD / H02_PORT / TRACCAR_WEB_PORT, with
real environment variables winning -- the same convention as scripts/backup.sh and
scripts/simulate-fleet.py, so it also works under Dokploy where there is no .env.

Exit codes:  0 the tracker is delivering positions
             1 a precondition failed, or nothing connected in time
             2 bad usage
"""

from __future__ import annotations

import argparse
import datetime as dt
import http.cookiejar
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Traccar's h02 listener. NOT configurable: the compose file maps the host's
# ${H02_PORT} onto this container port and nothing else, because Traccar opens
# h02 on 5013 out of the box. Mapping the host port to itself is exactly the bug
# in docs/UNIMPLEMENTED.md 7.8 -- the published port lands on Traccar's *watch*
# listener (5093) and the stack comes up healthy while decoding nothing.
H02_CONTAINER_PORT = 5013

# Default SMS password on these units. `8030000` is four zeros of password plus
# the three-digit command; a unit whose password was changed needs the new one.
DEFAULT_SMS_PASSWORD = "0000"

# The manual's documented reply to a successful setting command.
SMS_OK_REPLY = "SET OK"

# How often to ask Traccar whether the device has appeared. Traccar's own
# sampling is every few seconds, so polling faster only adds load.
POLL_SECONDS = 5

# A first GPS fix from cold can genuinely take this long, especially indoors or
# under a metal roof. Timing out earlier produces a false "it is broken".
DEFAULT_TIMEOUT_SECONDS = 900

# Traccar's public tool for testing a TCP port from outside the server's own
# network. We cannot test outside-in from here, and pretending to would be the
# same category of mistake as the watch-port bug.
PORT_CHECKER_URL = "https://www.traccar.org/port-check/"


# ---------------------------------------------------------------------------
# Pure logic. Everything below this line to the "I/O" banner is deterministic
# and tested in scripts/tests/test_connect_tracker.py -- no sockets, no docker,
# no clock. That is deliberate: the parts that decide *what to tell the
# operator* are the parts that must not be guessed at.
# ---------------------------------------------------------------------------

def load_env(path: str) -> None:
    """Load .env without clobbering real environment variables.

    Same convention as scripts/backup.sh and scripts/simulate-fleet.py. Under
    Dokploy there is no .env at all and the variables are already in the
    environment, which is the case this ordering exists for.
    """
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


def sms_sequence(
    apn: str,
    server: str,
    port: int,
    *,
    acc_interval: int = 20,
    parked_interval: int = 300,
    password: str = DEFAULT_SMS_PASSWORD,
    apn_user: str = "",
    apn_password: str = "",
) -> list[tuple[str, str]]:
    """The provisioning SMS for a SinoTrack ST-906L, in the documented syntax.

    The numeric form is what the ST-906L manual actually lists. The comma form
    (`apn,name#`, `server,0,host,port,0#`) that an earlier revision of
    docs/TRACKER-SETUP.md recommended belongs to other tracker families and is
    not in this model's manual -- sending an unrecognised command to a unit whose
    only configuration channel is SMS is not a harmless thing to do, so the
    sequence below is the documented one only.

    Order matters and is not cosmetic: APN first, because with no data session
    none of the rest can be observed taking effect. `7100000` selects GPRS mode
    explicitly rather than trusting the factory default. `RCONF` is the read-back
    -- it is the only way to know a setting took, since the only other evidence
    is a packet arriving on the server, which conflates six different faults.
    """
    if not apn:
        raise ValueError("apn is required")
    if not server:
        raise ValueError("server is required")
    if not 1 <= int(port) <= 65535:
        raise ValueError(f"port out of range: {port}")
    for label, seconds in (("ACC interval", acc_interval), ("parked interval", parked_interval)):
        # The manual gives a 10 s floor, and T=0 closes GPRS entirely -- which
        # reads as "the tracker is dead" on the server and is a real support
        # ticket. Refuse both rather than report them later as a hardware fault.
        if int(seconds) < 10:
            raise ValueError(
                f"{label} must be at least 10 seconds (0 closes GPRS); got {seconds}"
            )

    # The manual writes these as `8030000`, `8040000`, `8050000`, `8090000` and
    # `7100000`: a THREE-digit verb followed by the four-digit password. Splitting
    # it as `8030` + password gives five digits of verb and an eight-character
    # command the unit ignores silently -- which on an SMS-only interface looks
    # exactly like a dead SIM.
    pw = password or DEFAULT_SMS_PASSWORD
    apn_cmd = f"803{pw} {apn}"
    if apn_user:
        apn_cmd += f" {apn_user} {apn_password}"

    return [
        (apn_cmd, "set the carrier APN - send this one first"),
        (f"804{pw} {server} {int(port)}", "point the tracker at this server and port"),
        (f"805{pw} {int(acc_interval)}", "reporting interval with ignition on, seconds"),
        (f"809{pw} {int(parked_interval)}", "reporting interval with ignition off, seconds"),
        (f"710{pw}", "select GPRS mode explicitly instead of trusting the default"),
        ("RCONF", "read the settings back and check them on the reply"),
    ]


def device_payload(
    name: str,
    imei: str,
    *,
    model: str = "st-906l",
    category: str = "truck",
    phone: str = "",
) -> dict:
    """The Traccar device record.

    `uniqueId` is the field that has to match what the tracker sends in its login
    packet, and for these units that is the IMEI. A mismatch is the single most
    common reason a tracker reaches the server and still shows nothing: Traccar
    logs `Unknown device - <the identifier it read>` and stores no positions.

    `category` is not decoration. Traccar uses it to interpret computed values,
    and the wrong one produces misleading speeds and distances -- a tracker that
    reads 0 km/h while moving is usually just this.

    It has to be sent as the TOP-LEVEL `category` field. Putting it only in
    `attributes.deviceType` does nothing at all, which was measured on this stack
    (14 Oct 2026) rather than assumed:

        POST {attributes:{deviceType:'truck'}}       -> category: null
        POST {category:'truck', attributes:{...}}    -> category: 'truck'

    So this sent no category at all until that was found: every device this tool
    registered came out with a null category and Traccar fell back to its defaults
    for speed and distance. `deviceType` is kept as well -- it is harmless
    metadata, and the fleet simulator already writes it -- but it is not what sets
    the category, and a test asserts the payload carries both so neither can be
    dropped again by accident.
    """
    if not imei or not imei.strip():
        raise ValueError("imei (uniqueId) is required")
    if not name or not name.strip():
        raise ValueError("name is required")
    payload = {
        "name": name.strip(),
        "uniqueId": imei.strip(),
        "disabled": False,
        "category": category,
        "attributes": {"model": model, "deviceType": category},
    }
    if phone:
        payload["phone"] = phone
    return payload


def stage(device: dict | None, positions: list | None) -> str:
    """Which of the three states the device is in. The heart of the tool.

    These are genuinely different states and collapsing them is how "add a
    device" turns into an afternoon:

      registered  the record exists. It means nothing about the hardware.
      connected   the server has heard from it. `lastUpdate` moved, so a packet
                  was received and decoded into something -- this is strictly
                  stronger than `status`, which Traccar derives from its own
                  online window and which stays `offline` for a device that is
                  sending heartbeats.
      positioned  a real position is stored. Only this means it works.

    Deliberately NOT `status == 'online'` for `connected`: a research pass found
    H02 units sending `HTBT` heartbeats that never move the online flag, so
    treating status as the signal would report a working tracker as dead.
    """
    if not device:
        return "registered"
    if positions:
        return "positioned"
    if device.get("positionId"):
        return "positioned"
    return "connected" if device.get("lastUpdate") else "registered"


_UNKNOWN_DEVICE = re.compile(r"Unknown device\s*-\s*([^\s(]+)")
_TIMESTAMPED = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
# Any of these in a line means Traccar received protocol traffic from a device.
_TRAFFIC = re.compile(r"\b(?:HEX|TEXT):|\b(?:h02|gt06|watch)\b\s*[<>]", re.IGNORECASE)


def lines_since(log_text: str, since: dt.datetime | None) -> list[str]:
    """Keep only log lines at or after `since`.

    Without this the diagnosis reads the whole log tail and finds some other
    tracker's `Unknown device` warning from last week, then confidently tells the
    operator to rename the device to a stranger's IMEI. Traccar's log lines start
    with a timestamp and the container runs with TZ set, so this compares
    like-for-like naive local times.

    A line with no parseable timestamp is kept: Docker's own prefix, a stack
    trace and a multi-line exception all matter to the diagnosis, and dropping
    them would hide exactly the failure we are looking for.
    """
    if since is None:
        return [line for line in log_text.splitlines() if line.strip()]
    kept = []
    for line in log_text.splitlines():
        if not line.strip():
            continue
        match = _TIMESTAMPED.match(line.strip())
        if not match:
            kept.append(line)
            continue
        try:
            when = dt.datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            kept.append(line)
            continue
        if when >= since:
            kept.append(line)
    return kept


def diagnose(log_text: str, imei: str, since: dt.datetime | None = None) -> dict:
    """Read Traccar's log and say what actually went wrong.

    Three outcomes, and they are not interchangeable:

      no_traffic       nothing from any device in the window. The tracker never
                       reached the server: power, SIM, APN, the server address it
                       was pointed at, the firewall, or the port.
      unknown_device   a packet ARRIVED and Traccar read an identifier it does
                       not have a device for. This is not a connectivity fault at
                       all, and it has a one-line fix: the identifier in the
                       warning is what `uniqueId` has to be.
      reached_server   the server is talking to something it recognises, but no
                       position is stored: no GPS fix yet, heartbeat-only
                       traffic, or the wrong protocol/port.
    """
    window = lines_since(log_text, since)
    traffic_lines = [line for line in window if _TRAFFIC.search(line)]
    seen = []
    for line in window:
        match = _UNKNOWN_DEVICE.search(line)
        if match:
            identifier = match.group(1).strip().rstrip(",;")
            if identifier not in seen:
                seen.append(identifier)

    # Evidence about THIS device first. Traccar logs the protocol payload, and an
    # H02 payload carries the IMEI, so seeing our identifier in the log is direct
    # proof this unit reached the server. An `Unknown device` warning is the next
    # best evidence and means the opposite thing.
    #
    # Generic protocol traffic deliberately does NOT count. A log full of h02
    # packets may be a different vehicle entirely, and "the server is receiving
    # traffic it understands" is then a confidently wrong diagnosis that sends the
    # technician looking at the antenna while another tracker is working fine.
    our_lines = [line for line in window if imei and imei in line]
    if our_lines:
        kind = "reached_server"
    elif seen:
        kind = "unknown_device"
    else:
        kind = "no_traffic"

    return {
        "kind": kind,
        "seen_identifiers": seen,
        "traffic_lines": len(traffic_lines),
        "our_lines": len(our_lines),
        # A heartbeat is not a position, and on H02 it does not even move the
        # online flag. Worth naming separately so it is not read as success.
        "heartbeat_only": bool(our_lines) and all("HTBT" in line for line in our_lines),
    }


_ENTRY = re.compile(r"<entry key='([^']+)'>([^<]*)</entry>")


def parse_server_settings(xml_text: str) -> dict | None:
    """Read the auto-registration settings out of the rendered traccar.xml.

    The point is to stop advising from assumption. "Traccar does not auto-register
    unknown devices" is the right explanation on a default server and the WRONG one
    on a server where the switch is on and an allow-list turned this identifier
    away — the two need opposite fixes, and the operator cannot tell them apart
    from the symptom, which is identical.

    Returns None when the file could not be read, `register_unknown` is None when
    the key is absent (an older render, so nothing can be concluded).
    """
    if not xml_text:
        return None
    values = dict(_ENTRY.findall(xml_text))
    if not values:
        return None
    raw = (values.get("database.registerUnknown") or "").strip().lower()
    return {
        "register_unknown": None if not raw else raw == "true",
        "regex": (values.get("database.registerUnknown.regex") or "").strip(),
        "category": (values.get("database.registerUnknown.defaultCategory") or "").strip(),
    }


def matches_identifier(pattern: str, identifier: str) -> bool | None:
    """Would Traccar's allow-list accept this identifier?

    Traccar applies the pattern with Java's String.matches, which requires the
    WHOLE identifier to match -- the constant pool of ConnectionManager in the
    6.16 image calls java/lang/String.matches(Ljava/lang/String;)Z. Python's
    fullmatch has the same whole-string semantics, so it answers the operator's
    real question: is this the reason the tracker was turned away?

    Returns None when the pattern cannot be evaluated (unreadable, or syntax
    Python and Java spell differently), which is reported as "cannot tell" rather
    than as reassurance.
    """
    if not pattern or not identifier:
        return None
    try:
        return re.fullmatch(pattern, identifier) is not None
    except re.error:
        return None


def unknown_device_advice(seen: str, imei: str, settings: dict | None) -> list[str]:
    """Why an identifier that reached the server was refused, and what to do."""
    first = seen.split(",")[0].strip()
    lines = [
        f"Received a packet, but the identifier the server read is not a device: {seen}",
        f"  That identifier is what Traccar matches on. Register it instead of {imei}:",
        f"    ./scripts/connect-tracker.py --adopt-seen-id {first}",
    ]
    pattern = (settings or {}).get("regex") or ""
    auto = (settings or {}).get("register_unknown")
    if auto is True and pattern:
        verdict = matches_identifier(pattern, first)
        if verdict is True:
            lines.append(f"  Auto-registration is ON and {first} DOES match /{pattern}/, so the")
            lines.append("  refusal came from something else. Re-run and watch the log.")
        else:
            lines.append(f"  Auto-registration is ON, but only identifiers matching /{pattern}/ are")
            lines.append(f"  accepted, and {first} does not{' (the whole identifier must match)' if verdict is False else ' — note it must match the WHOLE identifier'}.")
            lines.append("  Either point the tracker at the identifier it is registered under, or")
            lines.append("  widen TRACCAR_REGISTER_UNKNOWN_REGEX and redeploy.")
    elif auto is True:
        lines.append("  Auto-registration is ON with no allow-list, so this identifier should have")
        lines.append("  been created. If it repeats, the packet itself is probably malformed --")
        lines.append("  check it starts with *HQ and ends with #.")
    else:
        lines.append("  Traccar does not auto-register unknown devices by default. See")
        lines.append("  docs/TRACKER-SETUP.md — if you want a tracker to appear on its own,")
        lines.append("  that is TRACCAR_REGISTER_UNKNOWN=true, and it is a deliberate trade-off.")
    return lines


def advice(result: dict, imei: str, server: str, port: int, sms_reply: str = "",
           server_settings: dict | None = None) -> list[str]:
    """Turn a diagnosis into the next action, specific to this failure."""
    kind = result.get("kind")
    lines = []
    if kind == "unknown_device":
        seen = ", ".join(result.get("seen_identifiers") or [])
        lines.extend(unknown_device_advice(seen, imei, server_settings))
    elif kind == "reached_server":
        lines.append("The server is receiving traffic it understands, but no position is stored.")
        lines.append("  * Send RCONF and read the reply. If the APN or the IP/port is wrong in it,")
        lines.append("    the settings never took -- and a silent SMS looks exactly like this.")
        lines.append("  * Take the tracker outdoors, antenna up. A cold first fix can take 15 minutes.")
        lines.append("  * An `A` in the position packet means a valid fix, `V` means none. All `V` is")
        lines.append("    an antenna problem, not a tracker problem.")
        lines.append("  * Confirm the protocol and port: h02 is 5013, and the packet must start")
        lines.append("    with *HQ and end with #.")
    elif kind == "no_traffic":
        lines.append("Nothing from any device reached the server. That is a device-side path,")
        lines.append("not a dashboard problem:")
        lines.append(f"  * From OUTSIDE this network, can you reach {server}:{port}?")
        lines.append(f"    {PORT_CHECKER_URL}")
        lines.append("  * The SIM is data-capable, has no PIN, is not out of data, and is not")
        lines.append("    roaming into a surcharge. Test it in a phone first.")
        lines.append("  * The APN is the carrier's, not a guess. A wrong APN is indistinguishable")
        lines.append("    from dead hardware because the unit has no screen.")
        lines.append("  * The server address stored in the tracker is the public one. `8040000`")
        lines.append("    takes an IP; a hostname is not documented for this model.")
        lines.append("  * RCONF and check MODE:GPRS, APN and IP:port on the reply.")
    else:
        lines.append("Unrecognised diagnosis state; read the Traccar log directly.")
    if sms_reply:
        lines.append(f"  * The tracker replied to your last SMS with: {sms_reply}")
        lines.append(f"    The documented success reply is {SMS_OK_REPLY!r}. Anything else, resend.")
    return lines


def provisioning_record(imei: str, name: str, apn: str, server: str, port: int, when: dt.datetime | None = None) -> str:
    """A row for the operator's own tracker record.

    Printed rather than written to a file on purpose. An IMEI identifies a SIM and
    the vehicle name is tied to an employee, so this belongs in a spreadsheet or a
    password manager -- never in this repository. docs/TRACKER-SETUP.md says the
    same thing about the table it describes.
    """
    stamp = (when or dt.datetime.now()).strftime("%Y-%m-%d")
    return f"{imei}\t{name}\t{stamp}\tAPN={apn}\tserver={server}:{port}\tRCONF verified: ?"


def published_h02_port(ports: dict | None, container_port: int = H02_CONTAINER_PORT) -> int | None:
    """The host port that reaches the container's h02 listener, from docker inspect.

    `docker inspect --format "{{json .NetworkSettings.Ports}}"` yields
    {"5013/tcp": [{"HostIp": "0.0.0.0", "HostPort": "5093"}], ...}. A key that is
    present with an EMPTY list means the port is EXPOSEd but not published — the
    silent failure this whole precondition exists to catch — so that returns None,
    not 0, and never looks like a successful mapping.
    """
    mapping = (ports or {}).get(f"{container_port}/tcp")
    if not mapping:
        return None
    try:
        host_port = int(mapping[0].get("HostPort", 0) or 0)
    except (AttributeError, TypeError, ValueError, IndexError):
        return None
    return host_port or None


def choose_container(candidates: list[tuple[str, int | None]], expected: int) -> str:
    """Pick the Traccar container that publishes `expected`, from (name, host_port).

    Discovering "the Traccar container" by taking the first name docker prints is
    wrong the moment two stacks run on one machine, and that is not hypothetical:
    it happened while testing this tool, where a second compose project held the
    H02 port this one was configured for. The failure it produces is worse than
    having no check at all — a port-mapping FAULT reported against a healthy
    stack sends the technician to edit a compose file that was already correct.

    Order of preference:

      1. the container publishing exactly the expected host port. Unambiguous,
         and the only case where the answer is certain.
      2. no expected port given: the first container publishing H02 anywhere.
      3. the first container publishing H02 somewhere else: better than nothing,
         and the mismatch is then reported as a real mismatch.
      4. the first container at all, so a stack with nothing published still gets
         a truthful "nothing is published to 5013/tcp" instead of "not found".

    Returns '' when there are no candidates.
    """
    if not candidates:
        return ""
    if expected:
        for name, host_port in candidates:
            if host_port == expected:
                return name
    for name, host_port in candidates:
        if host_port:
            return name
    return candidates[0][0]


# ---------------------------------------------------------------------------
# I/O: docker, sockets, the Traccar REST API.
# ---------------------------------------------------------------------------

_OPENER = urllib.request.build_opener(
    urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
)


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    """Run a command, returning (exit code, combined output). Never raises.

    A missing `docker` binary is a normal state on a technician's laptop, and the
    tool has to degrade to the checks it can still do rather than traceback.
    """
    try:
        done = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return 127, str(exc)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


class Api:
    """Traccar's REST API over a JSESSIONID cookie."""

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
        except urllib.error.URLError as exc:
            raise SystemExit(
                f"cannot reach Traccar at {self.base}: {exc.reason}. "
                "Is the stack up? (docker compose ps)"
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
        except urllib.error.URLError as exc:
            return {"_error": "unreachable", "_body": str(exc.reason)}


def traccar_candidates() -> list[tuple[str, int | None]]:
    """Every running Traccar container, with the host port publishing H02.

    Matched on the image rather than the container name: the compose project name
    is configurable (`-p gpstracer-dev`, and the documented default is
    `gpstracer-fleet`), so the container name is not something to hard-code.
    """
    code, out = run([
        "docker", "ps", "--filter", "ancestor=traccar/traccar", "--format", "{{.Names}}",
    ])
    names = out.split() if code == 0 else []
    if not names:
        # Fall back to a name match, which still works if the image was retagged.
        code, out = run(["docker", "ps", "--format", "{{.Names}}"])
        names = [n for n in out.split() if "traccar" in n.lower()] if code == 0 else []

    candidates = []
    for name in names:
        candidates.append((name, inspect_h02_port(name)))
    return candidates


def inspect_h02_port(container: str) -> int | None:
    """Host port publishing the container's h02 listener, or None."""
    code, out = run([
        "docker", "inspect", container, "--format", "{{json .NetworkSettings.Ports}}",
    ])
    if code != 0:
        return None
    try:
        return published_h02_port(json.loads(out.strip() or "{}"))
    except json.JSONDecodeError:
        return None


def find_traccar_container(explicit: str = "", expected: int = 0) -> str:
    """Name of the Traccar container to inspect, or '' if we cannot find one.

    With several stacks up, this returns the one that publishes `expected` rather
    than whichever docker happens to list first -- see choose_container.
    """
    if explicit:
        return explicit
    return choose_container(traccar_candidates(), expected)


def check_port_mapping(container: str, expected_host_port: int) -> dict:
    """Confirm the published H02 port actually reaches Traccar's h02 listener.

    This is the check that would have caught docs/UNIMPLEMENTED.md 7.8 before it
    shipped. `${H02_PORT}:${H02_PORT}` is a plausible-looking compose line that
    puts the tracker port on whatever *other* protocol Traccar happens to listen
    on at that number; the stack passes every healthcheck and decodes nothing.
    The only way to tell is to read the mapping and look at the container side.

    Returns {ok, host_port, container_port, detail}.
    """
    if not container:
        return {
            "ok": None,
            "host_port": None,
            "container_port": None,
            "detail": "no running Traccar container found; skipped (start the stack, or pass --container)",
        }
    code, out = run(["docker", "inspect", container, "--format", "{{json .NetworkSettings.Ports}}"])
    if code != 0:
        return {"ok": None, "host_port": None, "container_port": None, "detail": f"docker inspect failed: {out.strip()[:160]}"}
    try:
        ports = json.loads(out.strip() or "{}")
    except json.JSONDecodeError:
        return {"ok": None, "host_port": None, "container_port": None, "detail": "could not parse docker inspect output"}

    mapping = ports.get(f"{H02_CONTAINER_PORT}/tcp")
    if not mapping:
        return {
            "ok": False,
            "host_port": None,
            "container_port": None,
            "detail": (
                f"nothing is published to the container's h02 port {H02_CONTAINER_PORT}/tcp. "
                "The compose ports line must end in :5013, e.g. \"${H02_PORT:-5013}:5013\"."
            ),
        }
    host_port = int(mapping[0].get("HostPort", 0) or 0)
    if expected_host_port and host_port != expected_host_port:
        return {
            "ok": False,
            "host_port": host_port,
            "container_port": H02_CONTAINER_PORT,
            "detail": (
                f"the container's h02 port is published on host port {host_port}, but H02_PORT "
                f"says {expected_host_port}. The tracker would be sending to a port nothing "
                "is listening on."
            ),
        }
    return {
        "ok": True,
        "host_port": host_port,
        "container_port": H02_CONTAINER_PORT,
        "detail": f"host {host_port} -> container {H02_CONTAINER_PORT}/tcp (Traccar's h02 listener)",
    }


def tcp_reachable(host: str, port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """Can we open a TCP connection to the H02 port from here?

    Proves the mapping and the service, and nothing about the public internet:
    from the server's own network this succeeds even when a cloud firewall is
    blocking the world. That is why the outer test is named separately.
    """
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, f"TCP {host}:{port} accepts connections"
    except OSError as exc:
        return False, f"TCP {host}:{port} refused: {exc}"


def read_config_xml(container: str) -> str:
    """The rendered traccar.xml, for reading the settings actually in force.

    Read rather than assumed: the same symptom ("Unknown device") means either
    "auto-registration is off" or "the allow-list refused this identifier", and
    only the config says which. Returns '' if it cannot be read, and the caller
    then falls back to the default-accurate wording.
    """
    if not container:
        return ""
    code, out = run(
        ["docker", "exec", container, "cat", "/opt/traccar/conf/traccar.xml"], timeout=20
    )
    return out if code == 0 else ""


def read_server_log(container: str, tail: int = 4000) -> tuple[str, str]:
    """Traccar's log, from the file inside the container if we can get it.

    The file is preferred over `docker logs` because Traccar writes protocol
    traffic to its own log file and the container's stdout only carries a subset.
    Returns (text, source).
    """
    if container:
        code, out = run(
            ["docker", "exec", container, "sh", "-c",
             f"tail -n {int(tail)} /opt/traccar/logs/tracker-server.log"],
            timeout=25,
        )
        if code == 0 and out.strip():
            return out, f"{container}:/opt/traccar/logs/tracker-server.log"
    if container:
        code, out = run(["docker", "logs", container, "--tail", str(int(tail))], timeout=25)
        if code == 0 and out.strip():
            return out, f"docker logs {container}"
    return "", "unavailable"


def ensure_device(api: Api, imei: str, name: str, *, model: str, category: str) -> dict:
    """Register the tracker, or update it if it already exists.

    Idempotent on purpose: a technician who runs this twice should not get a
    database constraint violation, and a retry after a typo'd name should fix the
    name rather than create a second device.
    """
    existing = api.call(f"/devices?uniqueId={urllib.parse.quote(imei)}")
    if isinstance(existing, dict) and "_error" in existing:
        raise SystemExit(f"could not list devices: {existing}")
    if existing:
        device = existing[0]
        # Repair, not just rename: a device registered before the category fix
        # above has a null category, and re-running this tool is how an operator
        # would try to fix it. PUT takes the whole object, which is why the patch
        # is spread from the current one.
        patch = {**device}
        if device.get("name") != name:
            patch["name"] = name
        if (device.get("category") or "") != category:
            patch["category"] = category
        if patch != device:
            updated = api.call(f"/devices/{device['id']}", "PUT", patch)
            if isinstance(updated, dict) and "_error" in updated:
                raise SystemExit(f"could not update device: {updated}")
            device = updated if isinstance(updated, dict) else device
        return {"device": device, "created": False}

    created = api.call("/devices", "POST", device_payload(name, imei, model=model, category=category))
    if isinstance(created, dict) and "_error" in created:
        raise SystemExit(f"could not create device: {created}")
    return {"device": created, "created": True}


def watch(api: Api, device_id: int, *, timeout: int, started: dt.datetime, log, poll: int = POLL_SECONDS) -> dict:
    """Poll until the tracker is delivering positions, or give up.

    Reports a line each time the state changes, not on every poll: a wall of
    identical "waiting..." lines hides the one line that matters.
    """
    deadline = time.monotonic() + timeout
    last = None
    while True:
        device = api.call(f"/devices/{device_id}")
        if isinstance(device, dict) and "_error" in device:
            device = None
        positions = api.call(
            f"/positions?deviceId={device_id}"
            f"&from={started.strftime('%Y-%m-%dT%H:%M:%SZ')}"
            f"&to={(dt.datetime.utcnow() + dt.timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
        if isinstance(positions, dict):
            positions = []
        current = stage(device, positions)
        if current != last:
            log(current)
            last = current
        if current == "positioned":
            return {"stage": current, "device": device, "positions": len(positions)}
        if time.monotonic() >= deadline:
            return {"stage": current, "device": device, "positions": len(positions or [])}
        time.sleep(poll)


def watch_line(stage_name: str, elapsed: float) -> str:
    return {
        "registered": f"  [{elapsed:5.0f}s] registered — waiting for the tracker's first packet",
        "connected": f"  [{elapsed:5.0f}s] connected — the server has heard from it, waiting for a fix",
        "positioned": f"  [{elapsed:5.0f}s] positioned — real coordinates received",
    }.get(stage_name, f"  [{elapsed:5.0f}s] {stage_name}")


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="connect-tracker.py",
        description="Register a tracker with Traccar, print its SMS provisioning, and watch it connect.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  ./scripts/connect-tracker.py --check\n"
            "  ./scripts/connect-tracker.py --imei 4210209006 --name AB123CD --server vps.example.com --apn internet\n"
            "  ./scripts/connect-tracker.py --imei 4210209006 --watch-only\n"
            "  ./scripts/connect-tracker.py --adopt-seen-id 4210209006\n"
        ),
    )
    parser.add_argument("--imei", default="", help="the tracker's IMEI, as printed on the unit")
    parser.add_argument("--name", default="", help="Traccar device name, normally the plate (e.g. AB123CD)")
    parser.add_argument("--server", default=os.environ.get("TRACKER_SERVER", ""),
                        help="public host or IP the tracker should send to (no default: guessing this is how a fleet goes silent)")
    parser.add_argument("--apn", default=os.environ.get("TRACKER_APN", ""), help="the SIM's carrier APN")
    parser.add_argument("--apn-user", default="", help="APN username, only if the carrier requires one")
    parser.add_argument("--apn-password", default="", help="APN password, only if the carrier requires one")
    parser.add_argument("--h02-port", type=int, default=None, help="host side of the H02 mapping (default: H02_PORT from .env, else 5013)")
    parser.add_argument("--container", default="", help="Traccar container name, if discovery picks the wrong one")
    parser.add_argument("--acc-interval", type=int, default=20, help="reporting interval with ignition on, seconds (manual default 20)")
    parser.add_argument("--parked-interval", type=int, default=300, help="reporting interval with ignition off, seconds (manual default 300)")
    parser.add_argument("--sms-password", default=DEFAULT_SMS_PASSWORD, help="the unit's SMS password (factory default 0000)")
    parser.add_argument("--category", default="truck", help="Traccar device category; a wrong one distorts speeds and distances")
    parser.add_argument("--model", default="st-906l", help="Traccar device model (descriptive metadata)")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_SECONDS, help="seconds to wait for a position (default 900)")
    parser.add_argument("--poll", type=int, default=POLL_SECONDS, help="seconds between checks (default 5)")
    parser.add_argument("--check", action="store_true", help="only verify the server side; do not touch any device")
    parser.add_argument("--watch-only", action="store_true", help="skip registration; use the device that is already there")
    parser.add_argument("--print-sms", action="store_true", help="print the SMS provisioning block and exit")
    parser.add_argument("--adopt-seen-id", default="", metavar="IDENTIFIER",
                        help="set the named device's uniqueId to the identifier the server reported seeing")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    load_env(os.path.join(repo, ".env"))

    if args.h02_port is None:
        args.h02_port = int(os.environ.get("H02_PORT", H02_CONTAINER_PORT) or H02_CONTAINER_PORT)
    traccar_base = f"http://127.0.0.1:{os.environ.get('TRACCAR_WEB_PORT', '8082')}"

    report: dict = {"steps": {}, "ok": False}

    def emit(text: str = "") -> None:
        if not args.json:
            print(text)

    # ---- 1. server side -------------------------------------------------
    emit("1. Server side")
    candidates = traccar_candidates()
    container = args.container or choose_container(candidates, args.h02_port)
    if len(candidates) > 1 and not args.container:
        # Name the ambiguity instead of guessing silently: the operator can see
        # which stack was chosen, and can override with --container.
        emit(f"   note {len(candidates)} Traccar containers are running "
             f"({', '.join(n for n, _ in candidates)}); using {container}.")
    mapping = check_port_mapping(container, args.h02_port)
    report["steps"]["port_mapping"] = mapping
    if mapping["ok"] is True:
        emit(f"   ok   {mapping['detail']}")
    elif mapping["ok"] is None:
        emit(f"   warn {mapping['detail']}")
    else:
        emit(f"   FAIL {mapping['detail']}")
        if args.json:
            print(json.dumps(report, indent=1))
        return 1

    if args.server:
        reachable, detail = tcp_reachable(args.server, args.h02_port)
        report["steps"]["reachable"] = {"ok": reachable, "detail": detail}
        emit(f"   {'ok  ' if reachable else 'FAIL'} {detail}")
        emit(f"        (this is from here; only an outside test proves the public path: {PORT_CHECKER_URL})")
    else:
        emit("   --   no --server given, so reachability was not tested")

    # What the server will actually do with a tracker it has never seen. Worth
    # reporting before anything else is attempted: it decides whether the device
    # has to be registered here at all, and it is the one setting that changes the
    # meaning of the "Unknown device" warning further down.
    settings = parse_server_settings(read_config_xml(container))
    report["steps"]["auto_registration"] = settings
    if settings is None:
        emit("   --   traccar.xml unreadable, so the auto-registration state is unknown")
    elif settings["register_unknown"]:
        scope = (f"only identifiers matching /{settings['regex']}/" if settings["regex"]
                 else "any identifier")
        emit(f"   info auto-registration is ON ({scope}), category "
             f"{settings['category'] or '(unset)'} — a new tracker appears by itself")
    else:
        emit("   info auto-registration is OFF — a new tracker must be registered first.")
        emit("        That is the next step, and it is the default.")

    if args.check:
        report["ok"] = mapping["ok"] is not False
        if args.json:
            print(json.dumps(report, indent=1))
        return 0 if report["ok"] else 1

    # ---- 2. the tracker's own configuration -----------------------------
    complete = bool(args.imei and args.name)
    if args.print_sms or not complete:
        emit("")
        emit("2. Tracker provisioning SMS" + (
            "" if complete else "   (template: --imei, --name and --apn were not all given)"
        ))
        try:
            sequence = sms_sequence(
                args.apn or "<carrier-apn>",
                args.server or "<public-ip>",
                args.h02_port,
                acc_interval=args.acc_interval,
                parked_interval=args.parked_interval,
                password=args.sms_password,
                apn_user=args.apn_user,
                apn_password=args.apn_password,
            )
        except ValueError as exc:
            raise SystemExit(f"invalid provisioning input: {exc}")
        for command, purpose in sequence:
            emit(f"   {command:<42} {purpose}")
        emit("")
        emit(f"   Wait for {SMS_OK_REPLY!r} after each one, and do not send them in a different")
        emit("   order: with no data session nothing else can be observed taking effect.")
        emit("   Send RCONF afterwards and check the reply says MODE:GPRS and the APN and")
        emit("   IP:port you intended. Silence is not success.")
        report["steps"]["sms"] = [command for command, _ in sequence]

    if args.print_sms:
        if args.json:
            print(json.dumps(report, indent=1))
        return 0

    if not complete:
        emit("")
        emit("   Stopping here: --imei and --name are needed to register the device and watch")
        emit("   it connect. Add them and run again.")
        if args.json:
            print(json.dumps(report, indent=1))
        return 2

    api = Api(traccar_base)
    email = os.environ.get("ADMIN_EMAIL", "")
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or not password:
        raise SystemExit("ADMIN_EMAIL and ADMIN_PASSWORD must be set (.env) to use the API")
    api.login(email, password)

    # ---- 3. adopt an identifier the server actually saw -----------------
    if args.adopt_seen_id:
        existing = api.call(f"/devices?uniqueId={urllib.parse.quote(args.imei)}") if args.imei else []
        if not existing:
            raise SystemExit(
                f"--adopt-seen-id needs --imei of the device to change; "
                f"looking up {args.imei!r} found nothing"
            )
        device = existing[0]
        updated = api.call(f"/devices/{device['id']}", "PUT", {**device, "uniqueId": args.adopt_seen_id})
        if isinstance(updated, dict) and "_error" in updated:
            raise SystemExit(f"could not update uniqueId: {updated}")
        emit(f"   ok   {device['name']}: uniqueId {args.imei} -> {args.adopt_seen_id}")
        args.imei = args.adopt_seen_id
        report["steps"]["adopted"] = args.adopt_seen_id

    device_id = None
    if args.watch_only:
        found = api.call(f"/devices?uniqueId={urllib.parse.quote(args.imei)}")
        if not found:
            raise SystemExit(f"no device with uniqueId {args.imei}; drop --watch-only to create it")
        device_id = found[0]["id"]
        emit(f"   ok   watching existing device {found[0]['name']} (#{device_id})")
    else:
        result = ensure_device(api, args.imei, args.name, model=args.model, category=args.category)
        device_id = result["device"]["id"]
        report["steps"]["device"] = {"id": device_id, "created": result["created"]}
        emit(f"   {'ok' if result['created'] else 'ok  '} "
             f"{'created' if result['created'] else 'updated'} device #{device_id} "
             f"{args.name!r} uniqueId={args.imei} category={args.category}")

    # ---- 4. wait for the hardware ---------------------------------------
    emit("")
    emit(f"3. Waiting up to {args.timeout}s for the tracker to connect (Ctrl-C to stop)")
    started_local = dt.datetime.now()
    started_utc = dt.datetime.utcnow()

    def log_stage(name: str) -> None:
        if name != "registered":
            emit(watch_line(name, (dt.datetime.now() - started_local).total_seconds()))
        elif not args.json:
            emit(watch_line(name, 0.0))

    outcome = watch(api, device_id, timeout=args.timeout, started=started_utc, log=log_stage, poll=args.poll)
    report["steps"]["watch"] = {"stage": outcome["stage"], "positions": outcome["positions"]}
    emit("")

    if outcome["stage"] == "positioned":
        position = (outcome.get("device") or {})
        emit(f"   OK  {args.name} is delivering positions ({outcome['positions']} in the window).")
        emit("")
        emit("   Before fitting it to a vehicle, work through docs/TESTING.md. This proves the")
        emit("   server path, not the radio link, the antenna or the wiring.")
        emit("")
        emit("   Provisioning record for your own spreadsheet — NOT this repository:")
        emit("   " + provisioning_record(args.imei, args.name, args.apn or "?", args.server or "?", args.h02_port))
        report["ok"] = True
        if args.json:
            print(json.dumps(report, indent=1))
        return 0

    # ---- 5. it did not connect: say why --------------------------------
    emit(f"   No position after {args.timeout}s. Reading Traccar's log to find out why.")
    log_text, source = read_server_log(container)
    if not log_text:
        emit("   (could not read the server log; the advice below is generic)")
    diagnosis = diagnose(log_text, args.imei, since=started_local)
    report["steps"]["diagnosis"] = {**diagnosis, "log_source": source}
    if log_text:
        emit(f"   log source: {source}, {diagnosis['traffic_lines']} protocol line(s) "
             f"since this run started")
    emit("")
    for line in advice(diagnosis, args.imei, args.server or "<server>", args.h02_port,
                       server_settings=settings):
        emit("   " + line)
    if args.json:
        print(json.dumps(report, indent=1))
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nstopped")
        sys.exit(130)
