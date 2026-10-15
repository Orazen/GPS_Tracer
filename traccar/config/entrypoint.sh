#!/bin/sh
# ---------------------------------------------------------------------------
# Traccar entrypoint for GPS_Tracer.
#
# WHY THIS EXISTS
# ---------------
# Traccar 6.16 has no environment-variable configuration. There is no TRACCAR_*
# handling anywhere in tracker-server.jar (verified 30 Sep 2026 by scanning the
# jar's string table). It reads conf/traccar.xml and nothing else. So to keep
# secrets out of Git while still using a real config file, we render that file
# from environment variables at container start.
#
# The rendered file is written to a tmpfs-backed volume, never to the host, and
# is gitignored if it ever lands on disk.
#
# TWO FORMATTING TRAPS THAT CAUSE CRASH-LOOPS (both learned the hard way)
# ---------------------------------------------------------------------------
# 1. DOCTYPE. Java's java.util.Properties XML parser only accepts its own:
#        <!DOCTYPE properties SYSTEM 'http://java.sun.com/dtd/properties.dtd'>
#    Traccar's own traccar.dtd (which uses <traccar><property> elements) is
#    rejected with the deeply unhelpful "must contain the DOCTYPE declaration".
#
# 2. Single-line values. The Properties parser truncates any value containing a
#    newline. Multi-line values are silently cut off.
#
# Neither failure produces a useful error. The container just restarts.
# ---------------------------------------------------------------------------
set -eu

# Where the rendered config goes. Overridable so CI can render the file and read
# the XML back without a container: the two formatting traps in the header, and
# the registerUnknown companion keys, are only observable in the output.
# The default is where the image expects it, so a deployment never sets this.
CONF="${TRACCAR_CONF_PATH:-/opt/traccar/conf/traccar.xml}"

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${WEB_PORT:=8082}"
: "${LOG_LEVEL:=info}"
: "${POSITION_RETENTION_DAYS:=180}"
: "${ALLOW_REGISTRATION:=false}"
# Auto-create a device the first time an unknown identifier talks to the server,
# and what that device should look like. Rendered further down, below esc().
: "${REGISTER_UNKNOWN:=false}"
: "${REGISTER_UNKNOWN_CATEGORY:=truck}"
: "${REGISTER_UNKNOWN_REGEX:=}"
# off | nominatim | google | ... See GEOCODER_ENTRY below for why the default is
# off rather than the provider Traccar picks on its own.
: "${GEOCODER:=off}"

# Registration is closed by default. It exists only as a one-time bootstrap:
# Traccar creates NO users on a fresh install, and with registration off there is
# no way to create the first one, so the stack would come up "healthy" with
# nobody able to log in. See scripts/create-admin.sh and docs/DOKPLOY.md.
if [ "$ALLOW_REGISTRATION" = "true" ]; then
  REGISTRATIONS_ENTRY="true"
  echo "WARNING: registration is ENABLED. Anyone who reaches the dashboard can"
  echo "         create an account. Set TRACCAR_ALLOW_REGISTRATION=false and"
  echo "         redeploy once your administrator exists."
else
  REGISTRATIONS_ENTRY="false"
fi

# Escape the five XML entities. An unescaped & in a password breaks the file.
esc() {
  printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'
}

# database.registerUnknown. Traccar's default is off, and off is the right
# default here: the H02 port is on the public internet, so with this on, anything
# that opens a connection and sends a plausible packet becomes a device record
# and the roster fills with entries named after whatever the packet contained.
#
# Turning it on is the zero-touch onboarding path -- a tracker then appears by
# itself the moment it first connects, with no server-side step -- which is the
# right trade on a bench or a pilot and the wrong one for a production fleet.
# docs/TRACKER-SETUP.md §4 describes both paths and when each applies.
#
# On its own the switch is also incomplete, which was measured rather than
# assumed: a device auto-created with only `database.registerUnknown=true` comes
# out named after the raw identifier with an EMPTY category, and Traccar derives
# speed and distance from the category. So the switch is rendered together with
# the two keys that make the result correct and bounded:
#
#   defaultCategory  what kind of vehicle the new device is. `truck` here.
#   regex            an allow-list of identifiers. Empty means "any identifier",
#                    which is exactly what makes the switch a liability on a
#                    public port; `^42102` accepts this fleet's units and still
#                    rejects -- and still logs -- a stray packet from anything
#                    else. RECONF-verified IMEIs share a prefix less often than
#                    one would like, so this is a knob, not a default.
#
# This block sits below esc() because both values are interpolated into XML
# attributes, and every other value in this file is escaped the same way.
#
# Multi-line is safe here specifically because this is XML markup being spliced
# into the document, not a properties value -- see trap 2 in the header.
if [ "$REGISTER_UNKNOWN" = "true" ]; then
  REGISTER_UNKNOWN_ENTRY="    <entry key='database.registerUnknown'>true</entry>
    <entry key='database.registerUnknown.defaultCategory'>$(esc "$REGISTER_UNKNOWN_CATEGORY")</entry>"
  if [ -n "$REGISTER_UNKNOWN_REGEX" ]; then
    REGISTER_UNKNOWN_ENTRY="$REGISTER_UNKNOWN_ENTRY
    <entry key='database.registerUnknown.regex'>$(esc "$REGISTER_UNKNOWN_REGEX")</entry>"
  fi
  echo "WARNING: database.registerUnknown is ON. An unknown identifier that reaches"
  echo "         the H02 port will be created as a device automatically, as category"
  echo "         '$REGISTER_UNKNOWN_CATEGORY'${REGISTER_UNKNOWN_REGEX:+ and only if it matches /$REGISTER_UNKNOWN_REGEX/}."
  echo "         Set TRACCAR_REGISTER_UNKNOWN=false and redeploy for a production fleet."
  if [ -n "$REGISTER_UNKNOWN_REGEX" ]; then
    # Measured against 6.16: the identifier is tested with String.matches(), which
    # anchors BOTH ends. A prefix pattern like `^42102` therefore accepts nothing
    # at all, and it fails silently -- the tracker never appears and the log says
    # "Unknown device", which reads as a broken tracker rather than a typed regex.
    # Naming the semantics here is cheap; discovering it from that symptom is not.
    echo "         The pattern must match the WHOLE identifier (Traccar uses"
    echo "         String.matches), so '^42102' accepts nothing: write '42102.*'."
  fi
else
  REGISTER_UNKNOWN_ENTRY="    <entry key='database.registerUnknown'>false</entry>"
  if [ -n "$REGISTER_UNKNOWN_REGEX" ]; then
    # A silently ignored variable is a trap: the operator has every reason to
    # believe the allow-list is protecting the port, and it is not being read.
    echo "WARNING: TRACCAR_REGISTER_UNKNOWN_REGEX is set but TRACCAR_REGISTER_UNKNOWN is"
    echo "         not 'true'. The allow-list has no effect while auto-registration is off"
    echo "         (an unknown device is rejected before the regex is consulted)."
  fi
fi

# The JDBC URL needs its ampersands escaped too. Built separately because esc()
# would also escape the one inside the XML we are about to open.
JDBC_URL="jdbc:postgresql://db:5432/$(esc "$POSTGRES_DB")"

if [ "$POSITION_RETENTION_DAYS" = "0" ]; then
  echo "WARNING: POSITION_RETENTION_DAYS=0 disables automatic cleanup." >&2
  echo "         Location history will grow without bound. See docs/SECURITY.md." >&2
  RETENTION_ENTRY=""
else
  RETENTION_ENTRY="    <entry key='position.retention'>${POSITION_RETENTION_DAYS}</entry>"
fi

# Address lookup for the stops and trips reports.
#
# Traccar defaults to the public Nominatim service and, with no key set, resolves
# EVERY stop and trip of EVERY report through it. Three things follow, and all
# three were measured on this stack:
#
#   * it is slow. The same "stops" report took 15.4 s and 18.0 s on two
#     consecutive calls -- nothing is cached, because the lookups never succeed.
#   * it is rate limited. Nominatim answers HTTP 429, which is also what its
#     usage policy asks for at this request rate. A report is not a bulk lookup
#     service and the addresses come back empty anyway.
#   * it discloses data. Every lookup sends one of your customer's coordinates to
#     a third party. For a stack that deliberately keeps driver data at home,
#     that is a strange default to inherit by accident.
#
# So it is off unless asked for, and the stops and trips tables show a dash in the
# address column instead of waiting twenty seconds for one. Set GEOCODER to a
# provider and GEOCODER_KEY to its key to turn it on; the named providers and
# their keys are in Traccar's own documentation.
case "$GEOCODER" in
  off|false|none|"")
    GEOCODER_ENTRY="    <entry key='geocoder.enable'>false</entry>"
    ;;
  *)
    GEOCODER_ENTRY="    <entry key='geocoder.enable'>true</entry>
    <entry key='geocoder.type'>$(esc "$GEOCODER")</entry>"
    if [ -n "${GEOCODER_KEY:-}" ]; then
      GEOCODER_ENTRY="${GEOCODER_ENTRY}
    <entry key='geocoder.key'>$(esc "$GEOCODER_KEY")</entry>"
    fi
    if [ -z "${GEOCODER_KEY:-}" ] && [ "$GEOCODER" != "nominatim" ]; then
      echo "WARNING: GEOCODER=$GEOCODER usually needs GEOCODER_KEY; without one" >&2
      echo "         the lookups will fail and reports will be slow." >&2
    fi
    ;;
esac

cat > "$CONF" <<XML
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE properties SYSTEM 'http://java.sun.com/dtd/properties.dtd'>
<!-- Rendered at container start from environment variables. Do not commit. -->
<properties>

    <!-- Server -->
    <entry key='web.port'>$(esc "$WEB_PORT")</entry>
    <entry key='web.override'>/opt/traccar/web/override</entry>

    <!-- PostgreSQL. Not MySQL, not the embedded H2. -->
    <entry key='database.driver'>org.postgresql.Driver</entry>
    <entry key='database.url'>${JDBC_URL}</entry>
    <entry key='database.user'>$(esc "$POSTGRES_USER")</entry>
    <entry key='database.password'>$(esc "$POSTGRES_PASSWORD")</entry>

    <!-- Closed registration by default. Bootstrap-only; see entrypoint header. -->
    <entry key='registrations'>${REGISTRATIONS_ENTRY}</entry>

    <!-- Auto-create a device on an unknown identifier's first packet. Off by
         default; see the REGISTER_UNKNOWN block above. -->
${REGISTER_UNKNOWN_ENTRY}

    <!-- Forwarded-position age limit, seconds. Caps how far ahead of the device
         a position may be timestamped before it is rejected. -->
    <entry key='web.maxForwardAge'>300000</entry>

    <!-- Data retention. Days of position history. -->
${RETENTION_ENTRY}

    <!-- Address lookup for stops and trips. Off by default; see the header. -->
${GEOCODER_ENTRY}

    <!-- Logging -->
    <entry key='log.level'>$(esc "$LOG_LEVEL")</entry>
    <entry key='log.path'>/opt/traccar/logs</entry>

</properties>
XML

# Fail loudly here rather than as a mystery crash-loop.
if ! grep -q 'java.sun.com/dtd/properties.dtd' "$CONF"; then
  echo "FATAL: wrong DOCTYPE in rendered traccar.xml" >&2
  exit 1
fi
if grep -q 'CHANGE_ME' "$CONF"; then
  echo "FATAL: POSTGRES_PASSWORD is still CHANGE_ME. Set it in .env or Dokploy." >&2
  exit 1
fi

echo "Rendered $CONF (database: postgresql://db:5432/$POSTGRES_DB)"

# ---------------------------------------------------------------------------
# Publish the onboarding settings that were ACTUALLY rendered.
#
# The dashboard's "Connect a tracker" screen has to state what this server will
# do with an unknown identifier: whether it creates one, as what category, and
# against which allow-list. There are three ways to get that, and only one of
# them is right.
#
#   * Read conf/traccar.xml from the dashboard. No. That file also holds the
#     database password, and mounting it into the process that faces the browser
#     would hand a credential to the least trusted component here in order to
#     display a boolean.
#   * Read it from the environment. No. The dashboard container does not have
#     Traccar's environment, and duplicating those variables in two services is
#     exactly how the two drift apart with no error anywhere.
#   * Have the container that renders the file publish the values it used. That
#     is this, and it cannot disagree with the XML next to it, because both are
#     written from the same variables in the same process.
#
# It lands in the log directory because the dashboard already reads Traccar's log
# from there (it is where the `Unknown device` lines live) and so needs no extra
# mount. The file is rewritten on every start, so it cannot go stale, and it
# holds nothing secret: a boolean, a category name, and a pattern the operator
# typed into .env themselves.
#
# TRACCAR_STATUS_DIR exists so this can be asserted without a container, which is
# what CI does with it.
# ---------------------------------------------------------------------------
json_esc() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'
}

STATUS_FILE="${TRACCAR_STATUS_DIR:-/opt/traccar/logs}/onboarding.json"
mkdir -p "${STATUS_FILE%/*}" 2>/dev/null || true
if cat > "$STATUS_FILE" <<STATUS
{
  "writtenAt": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "allowRegistration": $([ "$ALLOW_REGISTRATION" = "true" ] && echo true || echo false),
  "registerUnknown": $([ "$REGISTER_UNKNOWN" = "true" ] && echo true || echo false),
  "defaultCategory": "$(json_esc "$REGISTER_UNKNOWN_CATEGORY")",
  "regex": "$(json_esc "$REGISTER_UNKNOWN_REGEX")",
  "h02ContainerPort": 5013
}
STATUS
then
  echo "Published the onboarding settings to $STATUS_FILE"
else
  echo "WARNING: could not write $STATUS_FILE, so the dashboard will report the" >&2
  echo "         registration state as unreadable rather than guessing at it." >&2
fi

# Hand over to the image's own command. Exec so Traccar becomes PID 1 and gets
# SIGTERM directly — Docker then stops it cleanly instead of killing it.
exec /opt/traccar/jre/bin/java -XX:+ExitOnOutOfMemoryError $JAVA_OPTS \
  -jar tracker-server.jar conf/traccar.xml
