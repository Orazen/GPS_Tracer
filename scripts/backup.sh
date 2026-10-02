#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# PostgreSQL backup and restore for GPS_Tracer.
#
#   ./scripts/backup.sh              # make a backup
#   ./scripts/backup.sh restore FILE # restore from a .sql.gz dump
#   ./scripts/backup.sh list         # show what is backed up
#
# Backups are written outside the repository (default /var/backups/gpstracer).
# Never commit a dump: it contains the whole fleet's location history.
#
# Restore is deliberately explicit and refuses to run non-interactively without
# --force, because it overwrites live data.
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."

# Load values from .env, letting real environment variables win.
#
# Dokploy has no .env file -- everything arrives as an environment variable -- so
# this must not require the file. And plain `source` overwrites unconditionally,
# which would make `BACKUP_DIR=/tmp/x ./backup.sh` silently do nothing.
#
# This is parsed line by line rather than sourced. An earlier version snapshotted
# every shell variable with `compgen -v`, then re-exported them -- which captured
# bash internals (BASH, BASH_ARGC, BASH_LINENO, ...) and left the shell unable to
# continue. Only genuinely-set names from the file are applied, and only when the
# environment does not already provide them.
load_env() {
  [ -f .env ] || return 0
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; *=*) ;; *) continue ;; esac
    key="${line%%=*}"
    value="${line#*=}"
    # strip one layer of matching quotes
    case "$value" in \"*\") value="${value#\"}"; value="${value%\"}" ;; \'*\') value="${value#\'}"; value="${value%\'}" ;; esac
    # A real environment variable always wins over the file.
    [ -n "${!key+x}" ] || export "$key=$value"
  done < .env
}
load_env

BACKUP_DIR="${BACKUP_DIR:-/var/backups/gpstracer}"
RETENTION="${BACKUP_RETENTION_DAYS:-14}"
# Compose project name. Must match how the stack was deployed.
PROJECT="${COMPOSE_PROJECT_NAME:-gpstracer}"
SERVICE="db"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

# Find the database container without assuming a project name.
db_container() {
  local c
  c="$(docker compose -p "$PROJECT" ps -q "$SERVICE" 2>/dev/null | head -1)"
  [ -z "$c" ] && c="$(docker ps --filter "ancestor=postgres:16-alpine" --format '{{.Names}}' | head -1)"
  [ -z "$c" ] && { echo "ERROR: cannot find the PostgreSQL container." >&2; exit 1; }
  printf '%s' "$c"
}

do_backup() {
  local c; c="$(db_container)"
  mkdir -p "$BACKUP_DIR"
  local out="$BACKUP_DIR/gpstracer-${STAMP}.sql.gz"

  echo "Backing up PostgreSQL from container '$c' ..."
  # Custom format via -Fc is smaller and restores far faster than plain SQL.
  # Compressed, so a 5M-position fleet stays manageable.
  if docker exec -e PGPASSWORD="$POSTGRES_PASSWORD" "$c" \
      pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --compress=9 \
      > "$out"; then
    # Verify it is not a zero-byte or truncated file. A silently empty backup is
    # worse than none, because it gives false confidence.
    local size; size=$(wc -c < "$out" | tr -d ' ')
    if [ "$size" -lt 1024 ]; then
      echo "ERROR: dump is only ${size} bytes — refusing to keep it as a backup." >&2
      rm -f "$out"
      exit 1
    fi
    chmod 600 "$out"
    echo "  wrote $out ($(du -h "$out" | cut -f1))"

    # Prune old dumps, but always keep at least the two most recent.
    if [ "$RETENTION" -gt 0 ]; then
      echo "  pruning dumps older than ${RETENTION} days ..."
      find "$BACKUP_DIR" -name 'gpstracer-*.sql.gz' -type f -mtime "+${RETENTION}" \
        -print -delete | sed 's/^/    removed /' || true
    fi
  else
    echo "ERROR: pg_dump failed. The database was not modified." >&2
    rm -f "$out"
    exit 1
  fi
}

do_restore() {
  local file="$1"
  [ -f "$file" ] || { echo "ERROR: no such file: $file" >&2; exit 1; }
  local c; c="$(db_container)"

  echo "This will OVERWRITE the live database '${POSTGRES_DB}'."
  echo "Dump: $file ($(du -h "$file" | cut -f1))"
  if [ "${2:-}" != "--force" ]; then
    read -r -p "Type the database name to confirm: " confirm
    [ "$confirm" = "$POSTGRES_DB" ] || { echo "Aborted."; exit 1; }
  fi

  # Stop Traccar so it is not writing while we replace the schema underneath it.
  # Restoring into a database that a running Traccar is actively writing to is how
  # you get a half-restored, inconsistent fleet.
  echo "Stopping Traccar ..."
  docker compose -p "$PROJECT" stop traccar >/dev/null 2>&1 || true

  # --clean --if-exists so objects absent from the dump are removed too; without
  # it, a restore leaves orphaned rows behind.
  echo "Restoring ..."
  if docker exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" "$c" \
      pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      --clean --if-exists --no-owner < "$file"; then
    echo "  restore complete."
  else
    echo "ERROR: pg_restore reported errors (see above)." >&2
    echo "       Traccar is still stopped. Fix the problem or re-run this script." >&2
    exit 1
  fi

  echo "Starting Traccar ..."
  docker compose -p "$PROJECT" start traccar >/dev/null 2>&1 || true
  echo "Done. Check the dashboard before walking away."
}

do_list() {
  if [ ! -d "$BACKUP_DIR" ]; then echo "No backup directory at $BACKUP_DIR."; return 0; fi
  echo "Backups in $BACKUP_DIR:"
  find "$BACKUP_DIR" -name 'gpstracer-*.sql.gz' -type f -printf '  %TY-%Tm-%Td %TH:%TM  %10s  %p\n' 2>/dev/null \
    || ls -lh "$BACKUP_DIR" | sed 's/^/  /'
}

case "${1:-backup}" in
  backup)          do_backup ;;
  restore)         [ -n "${2:-}" ] || { echo "Usage: $0 restore FILE [--force]" >&2; exit 1; }; do_restore "$2" "${3:-}" ;;
  list)            do_list ;;
  *)               echo "Usage: $0 [backup|restore FILE|list]" >&2; exit 1 ;;
esac
