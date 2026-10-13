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

CONF=/opt/traccar/conf/traccar.xml

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${WEB_PORT:=8082}"
: "${LOG_LEVEL:=info}"
: "${POSITION_RETENTION_DAYS:=180}"
: "${ALLOW_REGISTRATION:=false}"
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

# Hand over to the image's own command. Exec so Traccar becomes PID 1 and gets
# SIGTERM directly — Docker then stops it cleanly instead of killing it.
exec /opt/traccar/jre/bin/java -XX:+ExitOnOutOfMemoryError $JAVA_OPTS \
  -jar tracker-server.jar conf/traccar.xml
