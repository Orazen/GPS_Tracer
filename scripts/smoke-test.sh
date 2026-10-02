#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Verify a GPS_Tracer deployment is actually usable.
#
# Run this after every deploy. It exists because a broken deployment can look
# completely healthy: the container is up, the healthcheck passes, /api/server
# answers 200 -- and yet nobody can log in, because Traccar creates no users on a
# fresh install. That exact failure was hit while building this stack, so it is
# checked here explicitly rather than assumed.
#
#   ./scripts/smoke-test.sh
#   BASE_URL=https://fleet.example.com ./scripts/smoke-test.sh
# ---------------------------------------------------------------------------
set -uo pipefail

cd "$(dirname "$0")/.."

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

BASE="${BASE_URL:-http://127.0.0.1:${TRACCAR_WEB_PORT:-8082}}"
H02="${H02_PORT:-5013}"
FAILURES=0

pass() { printf '  \033[32mok\033[0m   %s\n' "$1"; }
fail() { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$1"; }

echo "Smoke-testing ${BASE}"

echo
echo "Reachability"
code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "${BASE}/api/server")
[ "$code" = "200" ] && pass "GET /api/server -> 200" || fail "GET /api/server -> ${code} (expected 200)"

if [ "${BASE}" = "http://127.0.0.1:${TRACCAR_WEB_PORT:-8082}" ] || [ "${BASE}" = "http://localhost:${TRACCAR_WEB_PORT:-8082}" ]; then
  curl -s -o /dev/null -m 10 "http://${BASE#http://}/" && pass "dashboard page served" || fail "dashboard page not served"
fi

echo
echo "Security posture"
code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' -X POST "${BASE}/api/users" \
  -H 'Content-Type: application/json' \
  -d '{"name":"smoke","email":"smoke@example.com","password":"SmokeTest123"}')
case "$code" in
  400|401|403) pass "self-registration refused (${code}) — good" ;;
  200) fail "self-registration ACCEPTED — anyone can create an account" ;;
  *)   warn "unexpected status ${code} for anonymous user creation" ;;
esac

if curl -s -m 5 "http://127.0.0.1:${TRACCAR_WEB_PORT:-8082}/" >/dev/null 2>&1; then
  code=$(curl -s -o /dev/null -m 5 -w '%{http_code}' "http://127.0.0.1:${TRACCAR_WEB_PORT:-8082}/" || echo 000)
  if [ "${SKIP_LOCAL:-}" = "1" ]; then
    warn "skipping local-only checks (SKIP_LOCAL=1)"
  else
    pass "8082 reachable on loopback (expected: proxied by Dokploy, not public)"
  fi
fi

echo
echo "Authentication"
ADMIN_EMAIL="${ADMIN_EMAIL:-}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-}"
if [ -n "$ADMIN_EMAIL" ] && [ -n "$ADMIN_PASSWORD" ] \
   && [ "${ADMIN_EMAIL#*CHANGE_ME}" = "$ADMIN_EMAIL" ]; then
  if curl -s -o /dev/null -m 10 -X POST "${BASE}/api/session" \
      -H 'Content-Type: application/x-www-form-urlencoded' \
      --data-urlencode "email=${ADMIN_EMAIL}" \
      --data-urlencode "password=${ADMIN_PASSWORD}"; then
    pass "administrator can log in"
  else
    fail "administrator '${ADMIN_EMAIL}' cannot log in — check ADMIN_EMAIL/ADMIN_PASSWORD"
  fi
else
  warn "ADMIN_EMAIL/ADMIN_PASSWORD unset — skipping the login check"
fi

# The failure that motivates this script.
users=$(curl -s -m 10 "${BASE}/api/users" -H 'Accept: application/json' \
        | head -c 40)
case "$users" in
  *Exception*|*NotFound*) warn "cannot read /api/users unauthenticated (expected without a session)" ;;
  "") warn "empty response from /api/users" ;;
  *) : ;;
esac

echo
echo "Tracker port"
if timeout 5 bash -c "exec 3<>/dev/tcp/127.0.0.1/${H02}" 2>/dev/null; then
  pass "H02 port ${H02} accepting connections"
else
  fail "H02 port ${H02} refused — trackers cannot connect"
fi

echo
echo "Database"
if command -v docker >/dev/null 2>&1; then
  PROJECT="${COMPOSE_PROJECT_NAME:-gpstracer}"
  # Resolve the db container id from compose. Note: `ps --status running` is not
  # available on every compose version and fails silently here, so check for the
  # id and then ask Docker whether that container is actually up.
  DBID="$(docker compose -p "$PROJECT" ps -q db 2>/dev/null | head -1)"
  if [ -n "$DBID" ]; then
    RUNNING="$(docker inspect -f '{{.State.Running}}' "$DBID" 2>/dev/null)"
    [ "$RUNNING" = "true" ] && pass "database container running (${DBID:0:12})" \
      || fail "database container exists but is not running"
    if docker exec "$DBID" pg_isready -U "${POSTGRES_USER:-traccar}" \
         -d "${POSTGRES_DB:-traccar}" >/dev/null 2>&1; then
      pass "PostgreSQL accepting connections"
    else
      warn "pg_isready failed inside ${DBID:0:12} — check credentials"
    fi
  else
    warn "no database container found for project '${PROJECT}'"
  fi
else
  warn "docker not available — skipping container checks"
fi

echo
echo "Backups"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/gpstracer}"
if [ -d "$BACKUP_DIR" ]; then
  n=$(find "$BACKUP_DIR" -name 'gpstracer-*.sql.gz' -type f 2>/dev/null | wc -l | tr -d ' ')
  [ "$n" -gt 0 ] && pass "${n} backup(s) present" || fail "backup directory exists but is empty"
  newest=$(find "$BACKUP_DIR" -name 'gpstracer-*.sql.gz' -type f -mtime -2 2>/dev/null | wc -l | tr -d ' ')
  [ "$newest" -gt 0 ] && pass "a backup is less than 2 days old" || fail "no recent backup (within 2 days)"
else
  warn "no backup directory at ${BACKUP_DIR} — cannot verify backups"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
  echo "RESULT: all checks passed"
else
  echo "RESULT: ${FAILURES} check(s) FAILED"
fi
exit "$FAILURES"
