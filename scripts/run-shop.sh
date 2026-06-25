#!/usr/bin/env bash
# Manage locally-running generated shops (shop_backend GraphQL + storefront).
#
# Usage:
#   ./scripts/run-shop.sh start <shop-name> [port]   (auto-picks a free port if omitted)
#   ./scripts/run-shop.sh list [-a|--all]    (-a also shows hostable but not running)
#   ./scripts/run-shop.sh stop <shop-name|all>
#   ./scripts/run-shop.sh restart <shop-name>
#   ./scripts/run-shop.sh logs <shop-name> [api|storefront]
#
# Shops run detached in the background; logs are written to .run/shops/.
# Use `logs` to tail them and `stop` to terminate.
#
# Layout (canonical, see shop_arena/src/shop_gen/pipeline.py):
#   outputs/shops/<shop-name>/data/       — SandboxShop dataset (store.json, ...)
#   outputs/shops/<shop-name>/<app-dir>/   — published storefront source (no deps)
#   outputs/shops/<shop-name>/runs/build/artifact/<app-dir>/   — build-loop tree (deps installed)
#
# The script hosts from runs/build/artifact/<app-dir>, where <app-dir> is read
# from .shop_gen/template.json and falls back to hydrogen for older shops.
# Override with STOREFRONT_DIR=<path> when you need a different tree.
# HYDROGEN_DIR=<path> remains supported for older Hydrogen-only workflows.
#
# Port convention: storefront runs on <port>, shop_backend on <port>+1000.
# Example: start mock_hardware 3001  → API:4001, storefront:3001
# When <port> is omitted, a free port is auto-picked from HYDROGEN_PORT_BASE
# upward (default 4100..4199; API: 5100..5199).

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="$REPO_ROOT/.run/shops"
mkdir -p "$RUN_DIR"

state_file() { echo "$RUN_DIR/$1.state"; }
log_file()   { echo "$RUN_DIR/$1.$2.log"; }

pid_alive() { [ -n "${1:-}" ] && kill -0 "$1" 2>/dev/null; }

# Open a URL in the default browser. Honors NO_OPEN=1.
open_url() {
  local url="$1"
  [ "${NO_OPEN:-0}" = "1" ] && return 0
  if command -v open >/dev/null 2>&1; then
    open "$url" >/dev/null 2>&1 || true
  elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$url" >/dev/null 2>&1 || true
  fi
}

read_state() {
  local sf; sf="$(state_file "$1")"
  API_PID=""; HYDROGEN_PID=""; PORT=""; API_PORT=""
  [ -f "$sf" ] || return 1
  # shellcheck disable=SC1090
  . "$sf"
}

write_state() {
  local name="$1" port="$2" api_port="$3" api_pid="$4" hyd_pid="$5"
  cat >"$(state_file "$name")" <<EOF
SHOP=$name
PORT=$port
API_PORT=$api_port
API_PID=$api_pid
HYDROGEN_PID=$hyd_pid
STARTED_AT=$(date +%s)
EOF
}

read_template_app_dir() {
  local shop_root="$1"
  local metadata="$shop_root/.shop_gen/template.json"
  if [ ! -f "$metadata" ]; then
    echo "hydrogen"; return 0
  fi
  node -e '
const fs = require("fs");
const metadataPath = process.argv[1];
let appDir = "hydrogen";
try {
  const value = JSON.parse(fs.readFileSync(metadataPath, "utf8")).app_dir;
  if (
    typeof value === "string" &&
    value.length > 0 &&
    !value.startsWith("/") &&
    !value.split("/").includes("..")
  ) {
    appDir = value;
  }
} catch {}
process.stdout.write(appDir);
' "$metadata"
}

# Recursively kill a PID and all its descendants
kill_tree() {
  local pid="${1:-}"
  [ -n "$pid" ] || return 0
  pid_alive "$pid" || return 0
  local kids=""
  if command -v pgrep >/dev/null 2>&1; then
    kids="$(pgrep -P "$pid" 2>/dev/null || true)"
  else
    kids="$(ps -o pid,ppid -ax 2>/dev/null | awk -v p="$pid" '$2==p{print $1}')"
  fi
  for k in $kids; do kill_tree "$k"; done
  kill "$pid" 2>/dev/null || true
}

# Auto-allocation range for storefront ports. API port = storefront + 1000.
# 4100..4199 / 5100..5199 avoids common collisions on dev machines
# (AirPlay 5000/7000, cbtemulator 9000, Kafka 9092/9093, ES 9200/9300).
HYDROGEN_PORT_BASE=${HYDROGEN_PORT_BASE:-4100}
HYDROGEN_PORT_COUNT=${HYDROGEN_PORT_COUNT:-100}

# True if any process is LISTENing on $1.
port_in_use() {
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

# Print a free storefront port (and its api=+1000 also free). Exits 1 if none.
pick_port() {
  local i p api
  for ((i=0; i<HYDROGEN_PORT_COUNT; i++)); do
    p=$((HYDROGEN_PORT_BASE + i))
    api=$((p + 1000))
    if ! port_in_use "$p" && ! port_in_use "$api"; then
      echo "$p"; return 0
    fi
  done
  return 1
}

cmd_start() {
  local name="${1:-}" port="${2:-}"
  if [ -z "$name" ]; then
    echo "Usage: $0 start <shop-name> [port]" >&2; exit 1
  fi

  if [ -z "$port" ]; then
    port="$(pick_port)" || {
      echo "❌ No free port in range $HYDROGEN_PORT_BASE..$((HYDROGEN_PORT_BASE+HYDROGEN_PORT_COUNT-1))" >&2
      exit 1
    }
    echo "ℹ Auto-allocated storefront port $port (api: $((port+1000)))"
  fi

  local api_port=$((port + 1000))
  local shop_root="$REPO_ROOT/outputs/shops/$name"
  local data_dir="$shop_root/data"
  local app_dir; app_dir="$(read_template_app_dir "$shop_root")"
  local artifact="$shop_root/runs/build/artifact/$app_dir"
  [ -d "$data_dir" ] || { echo "❌ Data dir not found: $data_dir" >&2; exit 1; }

  # STOREFRONT_DIR override > HYDROGEN_DIR compatibility override > artifact tree > error.
  local hyd_dir=""
  if [ -n "${STOREFRONT_DIR:-}" ]; then
    hyd_dir="$STOREFRONT_DIR"
    [ -d "$hyd_dir" ] || { echo "❌ STOREFRONT_DIR not a directory: $hyd_dir" >&2; exit 1; }
  elif [ -n "${HYDROGEN_DIR:-}" ]; then
    hyd_dir="$HYDROGEN_DIR"
    [ -d "$hyd_dir" ] || { echo "❌ HYDROGEN_DIR not a directory: $hyd_dir" >&2; exit 1; }
  elif [ -d "$artifact/node_modules" ]; then
    hyd_dir="$artifact"
  else
    {
      echo "❌ No hydrated storefront tree found for '$name' (template app: $app_dir). Tried:"
      echo "    $artifact/node_modules"
      echo "  Hydrate it with: (cd '$artifact' && pnpm install)"
      echo "  Or override: STOREFRONT_DIR=<path> $0 start $name $port"
    } >&2
    exit 1
  fi

  if read_state "$name"; then
    if pid_alive "$API_PID" || pid_alive "$HYDROGEN_PID"; then
      echo "⚠ $name already running — stopping first"
      cmd_stop "$name" >/dev/null
    fi
  fi

  # Pre-flight: refuse if either port is already bound (after auto-stop above,
  # so restarting the same shop on its own port still works).
  if port_in_use "$port"; then
    echo "❌ Storefront port $port is already bound:" >&2
    lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | sed 's/^/   /' >&2
    echo "   Pick another port, or omit the port arg to auto-allocate." >&2
    exit 1
  fi
  if port_in_use "$api_port"; then
    echo "❌ API port $api_port (storefront + 1000) is already bound:" >&2
    lsof -nP -iTCP:"$api_port" -sTCP:LISTEN 2>/dev/null | sed 's/^/   /' >&2
    echo "   Pick a different storefront port, or omit the port arg to auto-allocate." >&2
    exit 1
  fi

  local api_log hyd_log
  api_log="$(log_file "$name" api)"
  hyd_log="$(log_file "$name" storefront)"
  : >"$api_log"; :>"$hyd_log"

  echo "▶ shop_backend → http://localhost:$api_port  ($data_dir)"
  # Absolute data_dir: pnpm --filter shifts cwd into the package dir.
  ( cd "$REPO_ROOT" && exec pnpm --filter @shop-gym/shop-backend shop-backend \
      "$data_dir" "$api_port" >"$api_log" 2>&1 ) &
  local api_pid=$!
  disown "$api_pid" 2>/dev/null || true

  # Wait for API health
  local ok=0
  for _ in $(seq 1 40); do
    if curl -sf "http://localhost:$api_port/health" >/dev/null 2>&1; then ok=1; break; fi
    pid_alive "$api_pid" || break
    sleep 0.5
  done
  if [ "$ok" != "1" ]; then
    echo "❌ shop_backend failed to start. See $api_log" >&2
    kill_tree "$api_pid"
    exit 1
  fi

  echo "▶ Storefront   → http://localhost:$port  ($app_dir)"
  ( cd "$hyd_dir" && NODE_ENV=production PORT="$port" PUBLIC_STORE_DOMAIN="http://localhost:$api_port" \
      SHOP_BACKEND_URL="http://localhost:$api_port" \
      exec node server.mjs >"$hyd_log" 2>&1 ) &
  local hyd_pid=$!
  disown "$hyd_pid" 2>/dev/null || true

  # Wait for the storefront to start serving (server.mjs exposes /health).
  local hyd_ok=0
  for _ in $(seq 1 60); do
    if curl -sf "http://localhost:$port/health" >/dev/null 2>&1; then hyd_ok=1; break; fi
    pid_alive "$hyd_pid" || break
    sleep 0.5
  done
  if [ "$hyd_ok" != "1" ]; then
    echo "❌ Storefront failed to start. See $hyd_log" >&2
    kill_tree "$hyd_pid"
    kill_tree "$api_pid"
    exit 1
  fi

  write_state "$name" "$port" "$api_port" "$api_pid" "$hyd_pid"

  echo "✓ Started $name (storefront=$hyd_pid api=$api_pid)"
  echo "  storefront: http://localhost:$port"
  echo "  api:      http://localhost:$api_port"
  echo "  stop:     $0 stop $name"
  echo "  logs:     $0 logs $name [api|storefront]"

  open_url "http://localhost:$port"
}

cmd_stop() {
  local target="${1:-}"
  if [ -z "$target" ]; then
    echo "Usage: $0 stop <shop-name|all>" >&2; exit 1
  fi

  local names=()
  if [ "$target" = "all" ]; then
    shopt -s nullglob
    for sf in "$RUN_DIR"/*.state; do
      names+=("$(basename "$sf" .state)")
    done
    shopt -u nullglob
  else
    names=("$target")
  fi

  if [ ${#names[@]} -eq 0 ]; then
    echo "(nothing to stop)"; return 0
  fi

  for n in "${names[@]}"; do
    if ! read_state "$n"; then
      echo "— $n: no state file"; continue
    fi
    local stopped=0
    if pid_alive "$HYDROGEN_PID"; then kill_tree "$HYDROGEN_PID"; stopped=1; fi
    if pid_alive "$API_PID";      then kill_tree "$API_PID";      stopped=1; fi
    sleep 0.3
    pid_alive "$HYDROGEN_PID" && kill -9 "$HYDROGEN_PID" 2>/dev/null || true
    pid_alive "$API_PID"      && kill -9 "$API_PID"      2>/dev/null || true
    rm -f "$(state_file "$n")"
    if [ "$stopped" = "1" ]; then echo "✓ stopped $n"; else echo "— $n: not running (cleaned state)"; fi
  done
}

cmd_restart() {
  local name="${1:-}"
  [ -n "$name" ] || { echo "Usage: $0 restart <shop-name>" >&2; exit 1; }
  read_state "$name" || { echo "❌ $name is not tracked" >&2; exit 1; }
  local port="$PORT"
  cmd_stop "$name" >/dev/null
  cmd_start "$name" "$port"
}

cmd_list() {
  local show_all=0
  case "${1:-}" in -a|--all|all) show_all=1 ;; esac

  shopt -s nullglob
  local files=("$RUN_DIR"/*.state)
  shopt -u nullglob

  local tracked=" "
  if [ ${#files[@]} -gt 0 ]; then
    for sf in "${files[@]}"; do
      tracked+="$(basename "$sf" .state) "
    done
  fi

  if [ ${#files[@]} -eq 0 ] && [ "$show_all" != "1" ]; then
    echo "(no shops tracked — try: $0 list -a)"; return 0
  fi

  printf "%-35s %-8s %-8s %-10s %-10s %s\n" "SHOP" "PORT" "API" "HYD-PID" "API-PID" "STATUS"
  if [ ${#files[@]} -gt 0 ]; then
    for sf in "${files[@]}"; do
      local n; n="$(basename "$sf" .state)"
      read_state "$n" || continue
      local status="running"
      if ! pid_alive "$HYDROGEN_PID" && ! pid_alive "$API_PID"; then status="dead"
      elif ! pid_alive "$HYDROGEN_PID"; then status="hydrogen-down"
      elif ! pid_alive "$API_PID";      then status="api-down"
      fi
      printf "%-35s %-8s %-8s %-10s %-10s %s\n" "$n" "$PORT" "$API_PORT" "$HYDROGEN_PID" "$API_PID" "$status"
    done
  fi

  if [ "$show_all" = "1" ]; then
    local shops_dir="$REPO_ROOT/outputs/shops"
    [ -d "$shops_dir" ] || return 0
    for dir in "$shops_dir"/*/; do
      local sname; sname="$(basename "$dir")"
      [ "$sname" = "template" ] && continue
      [ -d "$dir/data" ] || continue
      local app_dir; app_dir="$(read_template_app_dir "${dir%/}")"
      [ -d "$dir/runs/build/artifact/$app_dir" ] || continue
      case "$tracked" in *" $sname "*) continue ;; esac
      printf "%-35s %-8s %-8s %-10s %-10s %s\n" "$sname" "-" "-" "-" "-" "available"
    done
  fi
}

cmd_logs() {
  local name="${1:-}" which="${2:-storefront}"
  [ "$which" = "hydrogen" ] && which="storefront"
  [ -n "$name" ] || { echo "Usage: $0 logs <shop-name> [api|storefront]" >&2; exit 1; }
  local f; f="$(log_file "$name" "$which")"
  [ -f "$f" ] || { echo "❌ No log: $f" >&2; exit 1; }
  tail -n 200 -f "$f"
}


sub="${1:-}"; shift || true
case "$sub" in
  start)   cmd_start   "$@" ;;
  stop)    cmd_stop    "$@" ;;
  restart) cmd_restart "$@" ;;
  list|ls|ps) cmd_list "$@" ;;
  logs)    cmd_logs    "$@" ;;
  ""|help|-h|--help)
    sed -n '2,19p' "$0" | sed 's/^# \{0,1\}//'
    ;;
  *) echo "Unknown command: $sub" >&2; exit 1 ;;
esac
