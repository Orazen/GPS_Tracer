#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Create the first Traccar administrator.
#
# WHY THIS IS NEEDED
# ------------------
# Traccar creates NO users on a fresh install. There is no default admin/admin
# account in 6.16 - verified against a clean PostgreSQL boot on 1 Oct 2026:
#
#   postgres=# SELECT count(*) FROM tc_users;
#            count
#              0
#
# With registration disabled (the correct production setting) there is then no
# way to create the first user: POST /api/users is refused for anonymous callers
# with a NullPointerException from PermissionsService, which is Traccar's way of
# saying "you are not allowed". The stack looks perfectly healthy - the
# healthcheck passes, /api/server answers - and is completely unusable.
#
# So the first run is a deliberate, documented three-step bootstrap:
#
#   1. TRACCAR_ALLOW_REGISTRATION=true   in .env, then:  docker compose up -d
#   2. ./scripts/create-admin.sh                        (this script)
#   3. TRACCAR_ALLOW_REGISTRATION=false  in .env, then:  docker compose up -d
#
# This script only calls Traccar's own API. It never writes to the database and
# never tries to reproduce Traccar's password hashing (PBKDF2WithHmacSHA256, 200k
# iterations - see docs/SECURITY.md). Hand-rolling that in shell is exactly how you
# ship a deployment where nobody can log in.
#
# Safe to re-run: it refuses if the user already exists.
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."

# Load values from .env, letting real environment variables win. Dokploy has no
# .env file, so values must come from the environment there. Parsed rather than
# sourced so pre-set variables are not overwritten.
load_env() {
  [ -f .env ] || return 0
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; *=*) ;; *) continue ;; esac
    key="${line%%=*}"; value="${line#*=}"
    case "$value" in \"*\") value="${value#\"}"; value="${value%\"}" ;; \'*\') value="${value#\'}"; value="${value%\'}" ;; esac
    [ -n "${!key+x}" ] || export "$key=$value"
  done < .env
}
load_env

WEB_PORT="${TRACCAR_WEB_PORT:-8082}"
BASE="http://127.0.0.1:${WEB_PORT}"

: "${ADMIN_NAME:=Fleet Administrator}"
: "${ADMIN_EMAIL:?ADMIN_EMAIL is not set. Set it in .env or pass it in the environment.}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD is not set. Set it in .env or pass it in the environment.}"

case "$ADMIN_EMAIL" in
  *CHANGE_ME*) echo "ERROR: ADMIN_EMAIL is still CHANGE_ME. Edit .env first." >&2; exit 1 ;;
esac
case "$ADMIN_PASSWORD" in
  *CHANGE_ME*) echo "ERROR: ADMIN_PASSWORD is still CHANGE_ME. Edit .env first." >&2; exit 1 ;;
esac

# JSON escaping for values we inject. A password with a quote or backslash would
# otherwise produce invalid JSON and a baffling 400.
json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

echo "Waiting for Traccar at ${BASE} ..."
for i in $(seq 1 60); do
  if curl -fsS -m 3 "${BASE}/api/server" >/dev/null 2>&1; then
    echo "  Traccar is up."
    break
  fi
  [ "$i" -eq 60 ] && { echo "ERROR: Traccar did not become ready in 5 minutes." >&2; exit 1; }
  sleep 5
done

# Do NOT pre-check whether registration is open.
# GET /api/server reports a field called "registration", but it is Traccar's
# server/cluster registration, NOT user self-registration. Trusting it made this
# script refuse to run while registration was in fact enabled - verified 1 Oct
# 2026. Attempting the POST and interpreting the response is simpler and correct.

# Already there? Then this bootstrap is done.
if curl -fsS -m 5 -X POST "${BASE}/api/session" \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-urlencode "email=${ADMIN_EMAIL}" \
      --data-urlencode "password=${ADMIN_PASSWORD}" >/dev/null 2>&1; then
  echo "Administrator '${ADMIN_EMAIL}' already exists and can log in."
  echo "You can set TRACCAR_ALLOW_REGISTRATION=false and redeploy."
  exit 0
fi

echo "Creating administrator '${ADMIN_EMAIL}' ..."
BODY=$(printf '{"name":"%s","email":"%s","password":"%s"}' \
  "$(json_escape "$ADMIN_NAME")" \
  "$(json_escape "$ADMIN_EMAIL")" \
  "$(json_escape "$ADMIN_PASSWORD")")

RESP=$(curl -sS -m 15 -o /tmp/gps-tracker-admin.json -w '%{http_code}' \
  -X POST "${BASE}/api/users" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json' \
  -d "$BODY")

case "$RESP" in
  200|201)
    # Traccar makes the first registered user an administrator. Confirm it,
    # because if that ever changes the account would silently have no rights.
    if grep -q '"administrator":true' /tmp/gps-tracker-admin.json; then
      echo "  created, and it IS an administrator."
    else
      echo "  WARNING: created, but Traccar did NOT mark it administrator."
      echo "           Log in and grant admin rights manually before continuing."
    fi
    echo
    echo "Verify the login works:"
    echo "  curl -i -X POST ${BASE}/api/session \\"
    echo "    -H 'Content-Type: application/x-www-form-urlencoded' \\"
    echo "    --data-urlencode 'email=${ADMIN_EMAIL}' \\"
    echo "    --data-urlencode 'password=***'"
    echo
    echo "NOW: set TRACCAR_ALLOW_REGISTRATION=false and redeploy."
    ;;
  *)
    # Traccar answers 400 with a NullPointerException from PermissionsService
    # when anonymous callers may not create users - its way of saying
    # registration is closed.
    if grep -q "PermissionsService" /tmp/gps-tracker-admin.json 2>/dev/null; then
      cat >&2 <<EOF
ERROR: Traccar refused to create the user, which means registration is closed.

  1. Set TRACCAR_ALLOW_REGISTRATION=true in .env
  2. docker compose up -d          (or let Dokploy redeploy)
  3. Re-run this script
  4. Set it back to false and redeploy again
EOF
      exit 1
    fi
    echo "ERROR: Traccar returned HTTP ${RESP}" >&2
    head -c 400 /tmp/gps-tracker-admin.json >&2 || true
    echo >&2
    exit 1
    ;;
esac
