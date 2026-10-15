#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Bring a whole GPS_Tracer stack up, in one command, from a fresh checkout.
#
#   ./scripts/setup.sh
#
# WHY THIS EXISTS
# ---------------
# Setting this stack up used to be four steps across three documents: copy .env
# and invent two secrets, bring the stack up, notice that Traccar creates no
# users on a fresh install, go back to .env and enable registration, bring it up
# again, run create-admin.sh, then remember to turn registration off again. Each
# step is documented, and the one people skip is the last one -- which leaves a
# public dashboard where anyone can create an account.
#
# So this script does all of it, in the safe order, and finishes by running the
# smoke test. It is safe to re-run: the second run detects the administrator and
# changes nothing.
#
# A SECOND COPY ON ONE HOST
# -------------------------
# Two stacks on one machine must not share volumes or ports. Both are handled:
#
#   ./scripts/setup.sh --env-file .env.shop2 -p gpstracer-shop2
#
# The project name prefixes every volume and every container, so the two copies
# cannot see each other's database, and the env file decides the ports. Every
# published port is checked before anything starts, and the port's current owner
# is named, because "address already in use" from deep inside Compose is the
# least useful error in this project.
#
# Usage:
#   ./scripts/setup.sh                        # the normal case
#   ./scripts/setup.sh --check                # preflight only; change nothing
#   ./scripts/setup.sh --env-file F -p NAME   # a second copy on the same host
#   ./scripts/setup.sh --no-admin             # start the stack, create no user
#
# Exit codes: 0 ready to use, 1 something failed, 2 bad usage.
# ---------------------------------------------------------------------------
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE=".env"
PROJECT=""
CHECK_ONLY=false
WITH_ADMIN=true
ASSUME_YES=false

usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
}

while [ $# -gt 0 ]; do
  case "$1" in
    --env-file)   ENV_FILE="${2:?--env-file needs a path}"; shift 2 ;;
    --env-file=*) ENV_FILE="${1#*=}"; shift ;;
    -p|--project) PROJECT="${2:?--project needs a name}"; shift 2 ;;
    --project=*)  PROJECT="${1#*=}"; shift ;;
    --check)      CHECK_ONLY=true; shift ;;
    --no-admin)   WITH_ADMIN=false; shift ;;
    -y|--yes)     ASSUME_YES=true; shift ;;
    -h|--help)    usage; exit 0 ;;
    *) echo "ERROR: unknown option '$1'" >&2; usage >&2; exit 2 ;;
  esac
done

say()  { printf '\n\033[1m%s\033[0m\n' "$1"; }
ok()   { printf '  \033[32mok\033[0m   %s\n' "$1"; }
note() { printf '       %s\n' "$1"; }
warn() { printf '  \033[33mwarn\033[0m %s\n' "$1"; }
die()  { printf '  \033[31mFAIL\033[0m %s\n' "$1" >&2; exit 1; }

# Same convention as backup.sh, smoke-test.sh and connect-tracker.py: values
# come from the env file, but a real environment variable wins, so the script
# behaves the same under Dokploy where there is no file at all.
load_env() {
  [ -f "$1" ] || return 0
  local line key value
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue ;; *=*) ;; *) continue ;; esac
    key="${line%%=*}"; value="${line#*=}"
    case "$value" in \"*\") value="${value#\"}"; value="${value%\"}" ;; \'*\') value="${value#\'}"; value="${value%\'}" ;; esac
    [ -n "${!key+x}" ] || export "$key=$value"
  done < "$1"
}

# A password that Compose can interpolate and Traccar can carry in XML.
# base64 is exactly the alphabet that survives both; `openssl rand -base64` never
# emits $ " ' \ or a space, which are the five characters that break traccar.xml.
random_secret() {
  local bytes="$1"
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 "$bytes" | tr -d '\n'
  elif command -v python3 >/dev/null 2>&1; then
    python3 -c "import base64,secrets,sys; print(base64.b64encode(secrets.token_bytes(int(sys.argv[1]))).decode(), end='')" "$bytes"
  else
    die "neither openssl nor python3 is available, so no secret can be generated"
  fi
}

# Replace a KEY= line in place. The value is base64, which contains no character
# that is special to sed's replacement text (no & or backslash), so | is a safe
# delimiter.
set_key() {
  local file="$1" key="$2" value="$3" tmp
  tmp="$(mktemp)"
  sed "s|^${key}=.*|${key}=${value}|" "$file" > "$tmp"
  mv "$tmp" "$file"
}

# Which process or container holds this port, or empty if it is free. Answering
# "who owns it" rather than "it is busy" is the difference between a one-line fix
# and an hour in Docker's error messages.
port_owner() {
  local port="$1" owner
  owner="$(docker ps --format '{{.Names}}\t{{.Ports}}' 2>/dev/null \
            | awk -v p=":${port}->" 'index($0, p) { print $1; exit }')"
  if [ -n "$owner" ]; then printf 'container %s' "$owner"; return 0; fi
  if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
    exec 3<&- 3>&- 2>/dev/null || true
    printf 'a local process on 127.0.0.1'; return 0
  fi
  return 1
}

# ===========================================================================
# 1. Preflight
# ===========================================================================
say "1. Preflight"

command -v docker >/dev/null 2>&1 || die "docker is not installed."
docker info >/dev/null 2>&1 || die "the Docker daemon is not reachable — start Docker, then re-run."
docker compose version >/dev/null 2>&1 || die "docker compose (v2) is not available."
ok "docker and docker compose are available"

if [ -f "$ENV_FILE" ]; then
  ok "environment file ${ENV_FILE} is present"
else
  note "${ENV_FILE} does not exist yet — it will be created from .env.example"
fi

COMPOSE=(docker compose --env-file "$ENV_FILE")
if [ -n "$PROJECT" ]; then
  COMPOSE+=(-p "$PROJECT")
  # The other scripts in here find containers by project name, so they have to be
  # told the same one. Without this, `-p` set up a stack and then smoke-test.sh
  # and backup.sh looked at the default project and reported it missing.
  export COMPOSE_PROJECT_NAME="$PROJECT"
  ok "compose project name: ${PROJECT}"
else
  note "compose project name: the default in docker-compose.yml (gpstracer-fleet)"
fi

if [ "$WITH_ADMIN" = true ]; then
  load_env "$ENV_FILE"

  # Every port this stack publishes. H02 is the only one the outside world needs,
  # and the other three are loopback only — but a busy port is a busy port.
  for pair in "DASHBOARD_PORT:8083:the dashboard" \
              "TRACCAR_WEB_PORT:8082:Traccar's own UI" \
              "H02_PORT:5013:the tracker protocol" \
              "TACHO_API_PORT:8084:the tachograph API"; do
    key="${pair%%:*}"; rest="${pair#*:}"; default="${rest%%:*}"; what="${rest#*:}"
    port="${!key:-$default}"
    if owner="$(port_owner "$port")"; then
      die "port ${port} (${what}) is already in use by ${owner}. Stop it, or choose another port in ${ENV_FILE}."
    fi
    ok "port ${port} is free (${what})"
  done
else
  load_env "$ENV_FILE"
fi

if [ "$CHECK_ONLY" = true ]; then
  say "Preflight only (--check): nothing was changed."
  exit 0
fi

# ===========================================================================
# 2. The environment file
# ===========================================================================
say "2. Configuration"

if [ ! -f "$ENV_FILE" ]; then
  [ -f .env.example ] || die ".env.example is missing, so ${ENV_FILE} cannot be created."
  cp .env.example "$ENV_FILE"
  ok "created ${ENV_FILE} from .env.example"
fi

# A generated secret has to be written to the file AND pushed into this shell.
# Only updating the file is not enough, and the failure is silent in the worst
# way: load_env earlier imported the placeholder from that same file, an exported
# variable beats the file inside Compose, and the stack then starts from the
# placeholder while the file looks correct. Traccar refuses to boot on
# POSTGRES_PASSWORD=CHANGE_ME, so here it crash-looped instead of connecting to a
# database with the wrong password — which is the only reason it was found.
generated=""
if grep -qE '^POSTGRES_PASSWORD=(CHANGE_ME)?$' "$ENV_FILE"; then
  POSTGRES_PASSWORD="$(random_secret 24)"
  set_key "$ENV_FILE" POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
  export POSTGRES_PASSWORD
  ok "generated POSTGRES_PASSWORD (24 bytes, base64)"
  generated="yes"
else
  ok "POSTGRES_PASSWORD is already set"
fi

if grep -qE '^TACHO_API_TOKEN=(CHANGE_ME)?$' "$ENV_FILE"; then
  TACHO_API_TOKEN="$(random_secret 32)"
  set_key "$ENV_FILE" TACHO_API_TOKEN "$TACHO_API_TOKEN"
  export TACHO_API_TOKEN
  ok "generated TACHO_API_TOKEN (32 bytes, base64) — the tachograph API refuses to start without it"
  generated="yes"
else
  ok "TACHO_API_TOKEN is already set"
fi

ADMIN_EMAIL_NEW=""
is_placeholder() { [ -z "$1" ] || grep -q 'CHANGE_ME' <<<"$1"; }

if [ "$WITH_ADMIN" = true ]; then
  # Re-read, because the file was just written to. Note what is deliberately NOT
  # here: an `unset`. Clearing these would throw away an ADMIN_EMAIL that came from
  # the environment — which is the one that must win, exactly as it does everywhere
  # else in this project, and the only option under Dokploy where there is no file.
  load_env "$ENV_FILE"

  if is_placeholder "${ADMIN_EMAIL:-}"; then
    if [ "$ASSUME_YES" = false ] && [ -t 0 ]; then
      printf '       Administrator email (you will sign in with this): '
      read -r ADMIN_EMAIL
      export ADMIN_EMAIL
    fi
    # Still the .env.example placeholder: refuse rather than create a real
    # account on a public dashboard under somebody else's address.
    if is_placeholder "${ADMIN_EMAIL:-}"; then
      die "ADMIN_EMAIL is not set. Put ADMIN_EMAIL=you@example.com in ${ENV_FILE}, or pass it in the environment."
    fi
  fi
  ok "administrator email: ${ADMIN_EMAIL}"
  set_key "$ENV_FILE" ADMIN_EMAIL "$ADMIN_EMAIL"

  if is_placeholder "${ADMIN_PASSWORD:-}"; then
    # Generated rather than prompted: a person asked to invent a password here
    # types a weak one, and this is the account that can see every driver's data.
    ADMIN_PASSWORD="$(random_secret 18)"
    set_key "$ENV_FILE" ADMIN_PASSWORD "$ADMIN_PASSWORD"
    export ADMIN_PASSWORD
    ADMIN_EMAIL_NEW="yes"
  fi
fi

if [ "$generated" = "yes" ]; then
  note "Secrets live in ${ENV_FILE}, which is gitignored. Never commit it."
fi

# ===========================================================================
# 3. Bring the stack up
# ===========================================================================
say "3. Starting the stack"
note "First run pulls images and builds the dashboard and tachograph images."

if curl -fsS -m 3 "http://127.0.0.1:${TRACCAR_WEB_PORT:-8082}/api/server" >/dev/null 2>&1; then
  ok "Traccar is already answering on port ${TRACCAR_WEB_PORT:-8082}"
else
  note "Waiting for Traccar to answer. This is the slow part, and it is not stuck."
fi

# Registration is opened for the bootstrap by passing the value into Compose's
# environment rather than editing the file. Environment wins over the env file, so
# the stored setting is never left switched on by a script that was interrupted.
if [ "$WITH_ADMIN" = true ]; then
  export TRACCAR_ALLOW_REGISTRATION=true
fi

"${COMPOSE[@]}" up -d --wait --wait-timeout 420 \
  || die "the stack did not reach a healthy state. Inspect it with: ${COMPOSE[*]} ps && ${COMPOSE[*]} logs traccar"
ok "every service is up and healthy"

# ===========================================================================
# 4. The first administrator, then close the door behind them
# ===========================================================================
if [ "$WITH_ADMIN" = true ]; then
  say "4. Administrator"

  # create-admin.sh is idempotent: it reports an existing account and exits 0.
  ADMIN_NAME="${ADMIN_NAME:-Fleet Administrator}" \
  ADMIN_EMAIL="$ADMIN_EMAIL" ADMIN_PASSWORD="$ADMIN_PASSWORD" \
    ./scripts/create-admin.sh

  # And now shut the door. This is the step a person forgets, so it is not left
  # to a person: without this the dashboard is on the network accepting signups.
  unset TRACCAR_ALLOW_REGISTRATION
  "${COMPOSE[@]}" up -d --wait --wait-timeout 180 traccar >/dev/null
  ok "registration closed again (TRACCAR_ALLOW_REGISTRATION is false in ${ENV_FILE})"
fi

# ===========================================================================
# 5. Prove it, then say what to do next
# ===========================================================================
say "5. Smoke test"

smoke_rc=0
TRACCAR_WEB_PORT="${TRACCAR_WEB_PORT:-8082}" DASHBOARD_PORT="${DASHBOARD_PORT:-8083}" \
  ./scripts/smoke-test.sh || smoke_rc=$?

cat <<EOF

$(say "Ready.")

  Dashboard            http://127.0.0.1:${DASHBOARD_PORT:-8083}
  Traccar's own UI     http://127.0.0.1:${TRACCAR_WEB_PORT:-8082}   (break-glass, loopback only)
  Tachograph API       http://127.0.0.1:${TACHO_API_PORT:-8084}     (loopback only)

  Sign in as           ${ADMIN_EMAIL:-see ADMIN_EMAIL in ${ENV_FILE}}
EOF

if [ -n "${ADMIN_EMAIL_NEW:-}" ]; then
  cat <<EOF
  Password             ${ADMIN_PASSWORD}
                       generated, and stored in ${ENV_FILE}. Change it after the
                       first sign-in if anyone else has access to this machine.
EOF
fi

cat <<EOF

Next, with no hardware at all — a six-truck demo fleet, driven through the real
H02 decoder so every screen downstream of a stored position is exercised:

  ${COMPOSE[*]} --profile tools run --rm simulator --reset

Then, with a tracker on the bench — registers the device, prints the exact SMS
sequence with your APN and server substituted, and waits for a real position:

  ./scripts/connect-tracker.py --check
  ./scripts/connect-tracker.py --imei <imei> --name <plate> --server <public-ip> --apn <carrier-apn>

Nothing above proves the hardware works. Before wiring anything into a vehicle,
open docs/connect-hardware.html — the whole path on one page, with the failure
that each hop produces and the one command that checks it.
EOF

if [ "$smoke_rc" -ne 0 ]; then
  say "The smoke test reported ${smoke_rc} problem(s) — see above. The stack is up, but check those before relying on it."
  exit 1
fi

exit 0
