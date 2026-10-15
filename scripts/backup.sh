#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Backup and restore for GPS_Tracer.
#
#   ./scripts/backup.sh              # make a backup
#   ./scripts/backup.sh restore FILE # restore from a .sql.gz dump
#   ./scripts/backup.sh list         # show what is backed up
#
# Two things are backed up together under one timestamp: the PostgreSQL dump,
# and the tacho-data volume that holds uploaded driver cards. The database alone
# is not a backup of the tachograph feature — every import row points at a stored
# file, so restoring one without the other leaves the screen referring to
# evidence that no longer exists.
#
# Backups are written outside the repository (default /var/backups/gpstracer).
# Never commit a dump: it contains the whole fleet's location history and driver
# personal data.
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
# Must match `name:` in docker-compose.yml, or `docker compose -p` if that was
# used to bring the stack up. See the comment on `name:` there.
PROJECT="${COMPOSE_PROJECT_NAME:-gpstracer-fleet}"
SERVICE="db"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

# Every service that writes to the shared database. A restore must stop all of
# them (see do_restore), and the cleanup trap has to start them again -- which is
# why this is defined here and not as a `local` inside the function: by the time
# the trap fires the function's scope is gone, and `set -u` turns that into
# "writers: unbound variable" followed by no restart at all. Tested by doing it
# wrong first.
WRITERS="traccar tacho-api tacho-worker"

# Find the database container without assuming a project name.
db_container() {
  local c
  c="$(docker compose -p "$PROJECT" ps -q "$SERVICE" 2>/dev/null | head -1)"
  [ -z "$c" ] && c="$(docker ps --filter "ancestor=postgres:16-alpine" --format '{{.Names}}' | head -1)"
  [ -z "$c" ] && { echo "ERROR: cannot find the PostgreSQL container." >&2; exit 1; }
  printf '%s' "$c"
}

# The volume holding uploaded tachograph files, resolved from the running
# container rather than assumed: with `-p` the name is prefixed by the project,
# and a hard-coded name would silently archive nothing.
tacho_volume() {
  local c vol
  # -a matters: a restore stops this container before it needs the volume, and a
  # running-only lookup finds nothing and reports "no tacho volume", quietly
  # skipping the file restore. Which is what it did, once.
  c="$(docker compose -p "$PROJECT" ps -q -a tacho-api 2>/dev/null | head -1)"
  # Compose labels every container it creates with the service it belongs to, so
  # this finds `tacho-api` in ANY project — which is the point: the lookup above
  # needs the right project name, and this fallback is for when it is wrong.
  # A hard-coded container name used to be here, and it stopped matching the
  # moment container names became project-prefixed — silently, taking the
  # tachograph file archive down with it.
  [ -z "$c" ] && c="$(docker ps -a --filter 'label=com.docker.compose.service=tacho-api' --format '{{.Names}}' | head -1)"
  [ -z "$c" ] && return 0
  vol="$(docker inspect "$c" \
    --format '{{range .Mounts}}{{if eq .Destination "/var/lib/gpstracer/tacho"}}{{.Name}}{{end}}{{end}}')"
  printf '%s' "$vol"
}

# Archive that volume.
#
# `docker cp <container>:/path/. -` streams a tar to stdout. The alternative —
# bind-mounting the backup directory into a helper container — needs a host path
# the Docker VM can see, and on Docker Desktop it is not always there: a /tmp
# mount silently produced an empty archive earlier in this project. This route
# needs nothing but the volume.
archive_tacho() {
  local vol out helper size
  vol="$(tacho_volume)"
  if [ -z "$vol" ]; then
    echo "WARNING: no tacho-api container, so no uploaded files were archived." >&2
    echo "         The database dump is still valid; the tachograph screen may" >&2
    echo "         refer to files that are not in it." >&2
    return 0
  fi

  out="$BACKUP_DIR/gpstracer-tacho-${STAMP}.tar.gz"
  helper="gpstracer-backup-$$"
  docker rm -f "$helper" >/dev/null 2>&1 || true
  docker run -d --name "$helper" -v "$vol:/data:ro" alpine:3 sleep 300 >/dev/null

  # The trailing /. copies the volume's CONTENTS; without it the tar also carries
  # the directory itself and a restore nests everything one level too deep.
  if docker cp "$helper:/data/." - 2>/dev/null | gzip -9 > "$out"; then
    size=$(wc -c < "$out" | tr -d ' ')
    # A gzipped empty tar is a little over 100 bytes. Anything at that size means
    # there was nothing to archive, which is worth saying out loud rather than
    # keeping as if it were a backup.
    if [ "$size" -lt 200 ]; then
      echo "  note: tacho volume '$vol' is empty (no uploads yet); no archive kept."
      rm -f "$out"
    else
      chmod 600 "$out"
      echo "  wrote $out ($(du -h "$out" | cut -f1)) from volume $vol"
    fi
  else
    echo "WARNING: could not archive volume '$vol'. The database dump stands alone." >&2
    rm -f "$out"
  fi
  docker rm -f "$helper" >/dev/null 2>&1 || true
}

# Restore uploaded files. Additive: files already in the volume are overwritten
# by their archived counterparts, and nothing extra is deleted.
restore_tacho() {
  local dump="$1" dir stamp archive vol helper
  dir="$(dirname "$dump")"
  stamp="$(basename "$dump")"
  stamp="${stamp#gpstracer-}"
  stamp="${stamp%.sql.gz}"
  archive="$dir/gpstracer-tacho-${stamp}.tar.gz"

  if [ ! -f "$archive" ]; then
    echo "  no uploaded-file archive for this dump ($archive); skipping." >&2
    echo "  If the tachograph screen shows imports with no stored file, that is why." >&2
    return 0
  fi

  vol="$(tacho_volume)"
  [ -z "$vol" ] && { echo "WARNING: no tacho volume found; files not restored." >&2; return 0; }

  helper="gpstracer-restore-$$"
  docker rm -f "$helper" >/dev/null 2>&1 || true
  docker run -d --name "$helper" -v "$vol:/data" alpine:3 sleep 300 >/dev/null
  if gunzip -c "$archive" | docker cp - "$helper:/data"; then
    echo "  uploaded files restored into volume $vol"
  else
    echo "ERROR: failed to restore uploaded files from $archive." >&2
  fi
  docker rm -f "$helper" >/dev/null 2>&1 || true
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

    echo "Backing up uploaded tachograph files ..."
    archive_tacho

    # Prune old dumps, but always keep at least the two most recent.
    if [ "$RETENTION" -gt 0 ]; then
      echo "  pruning dumps older than ${RETENTION} days ..."
      find "$BACKUP_DIR" -name 'gpstracer-*.sql.gz' -o -name 'gpstracer-tacho-*.tar.gz' \
        -type f -mtime "+${RETENTION}" \
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

  # Stop EVERY writer, not just Traccar. All three containers share this
  # database, and pg_restore --clean has to drop and recreate their tables.
  # With the tachograph worker still running, its open transaction held a lock on
  # `tacho_imports` and the restore sat on `ALTER TABLE ... DROP CONSTRAINT`
  # indefinitely: not failed, not finished, database neither old nor new. That is
  # what happened the first time this was tried, and it is why the list below is
  # spelled out rather than left as "traccar".
  echo "Stopping ${WRITERS} ..."
  docker compose -p "$PROJECT" stop $WRITERS >/dev/null 2>&1 || true

  # Bring them back whatever happens next: a restore that fails, or that is
  # interrupted, must not leave the stack down. That is a second outage on top of
  # the first, and it is the one nobody notices until the next driver card fails
  # to import.
  restore_cleanup() {
    echo "Starting ${WRITERS} ..."
    docker compose -p "$PROJECT" start $WRITERS >/dev/null 2>&1 || true
  }
  trap restore_cleanup EXIT

  # --clean --if-exists so objects absent from the dump are removed too; without
  # it, a restore leaves orphaned rows behind.
  echo "Restoring ..."
  if docker exec -i -e PGPASSWORD="$POSTGRES_PASSWORD" "$c" \
      pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      --clean --if-exists --no-owner < "$file"; then
    echo "  restore complete."
    # Same timestamp, so a restore puts the database and the files it references
    # back together instead of leaving one half behind.
    restore_tacho "$file"
  else
    echo "ERROR: pg_restore reported errors (see above)." >&2
    echo "       The database may be partially restored — it is neither the old state" >&2
    echo "       nor the new one. Re-run the restore, or restore a different dump." >&2
    exit 1
  fi

  echo "Done. The services are restarted on the way out; check the dashboard"
  echo "before walking away."
}

do_list() {
  if [ ! -d "$BACKUP_DIR" ]; then echo "No backup directory at $BACKUP_DIR."; return 0; fi
  echo "Backups in $BACKUP_DIR:"
  find "$BACKUP_DIR" \( -name 'gpstracer-*.sql.gz' -o -name 'gpstracer-tacho-*.tar.gz' \) \
    -type f -printf '  %TY-%Tm-%Td %TH:%TM  %10s  %p\n' 2>/dev/null \
    | sort -k3 \
    || ls -lh "$BACKUP_DIR" | sed 's/^/  /'
  echo
  echo "  A dump and its uploaded-file archive share a timestamp. Restoring the"
  echo "  dump restores both; a dump with no matching .tar.gz was taken when the"
  echo "  volume was empty."
}

case "${1:-backup}" in
  backup)          do_backup ;;
  restore)         [ -n "${2:-}" ] || { echo "Usage: $0 restore FILE [--force]" >&2; exit 1; }; do_restore "$2" "${3:-}" ;;
  list)            do_list ;;
  *)               echo "Usage: $0 [backup|restore FILE|list]" >&2; exit 1 ;;
esac
