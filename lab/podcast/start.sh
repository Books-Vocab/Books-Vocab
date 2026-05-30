#!/usr/bin/env bash
# Start or restart the podcast pipeline monitor dashboard.
#
# Usage:
#   ./start.sh              # foreground · logs stream to terminal · Ctrl-C stops
#   ./start.sh 9000         # custom port (still foreground)
#   ./start.sh --bg [port]  # background · logs → monitor.log · returns immediately
#   ./start.sh --stop       # kill any running instance, exit
#
# Idempotent: a running instance on the same port is killed before a new one
# starts. The --bg mode is what `pipeline.py:_ensure_dashboard_running()`
# uses; humans should use the default (foreground) so they can SEE what the
# server is doing.

set -euo pipefail

cd "$(dirname "$0")"

LOG="monitor.log"
PID_FILE=".monitor.pid"
PORT=8765
MODE="fg"

# ── Parse args ──────────────────────────────────────────────────────────────
for arg in "$@"; do
  case "$arg" in
    --stop) MODE="stop" ;;
    --bg|-d|--detach) MODE="bg" ;;
    --fg) MODE="fg" ;;  # explicit, same as default
    *[0-9]*) PORT="$arg" ;;
    *) echo "unknown arg: $arg" >&2; exit 2 ;;
  esac
done

kill_existing() {
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "→ stopping monitor (pid $pid)"
      kill "$pid" 2>/dev/null || true
      for _ in 1 2 3 4 5 6; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi

  # Belt-and-suspenders: kill anything still on the port.
  local port_pids
  port_pids="$(lsof -t -i ":$PORT" 2>/dev/null || true)"
  if [[ -n "$port_pids" ]]; then
    echo "→ port $PORT was occupied by pid(s): $port_pids — killing"
    kill $port_pids 2>/dev/null || true
    sleep 1
    kill -9 $port_pids 2>/dev/null || true
  fi
}

if [[ "$MODE" == "stop" ]]; then
  kill_existing
  echo "monitor stopped"
  exit 0
fi

kill_existing

# ── Background mode (pipeline.py auto-launch path) ──────────────────────────
if [[ "$MODE" == "bg" ]]; then
  echo "→ starting monitor on port $PORT (background)"
  nohup uv run monitor/server.py --port "$PORT" > "$LOG" 2>&1 &
  NEW_PID=$!
  echo "$NEW_PID" > "$PID_FILE"
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/" 2>/dev/null | grep -q 200; then
      echo "✓ monitor ready · http://127.0.0.1:$PORT/"
      echo "  log: $(pwd)/$LOG"
      echo "  pid: $NEW_PID"
      exit 0
    fi
    sleep 0.5
  done
  echo "✗ monitor did not become ready in 5s — check $LOG"
  tail -20 "$LOG" || true
  exit 1
fi

# ── Foreground mode (default — human use) ───────────────────────────────────
echo "→ starting monitor on port $PORT (foreground · Ctrl-C to stop)"
echo "  http://127.0.0.1:$PORT/"
echo

# Record PID so a parallel --bg or --stop can still find us.
echo $$ > "$PID_FILE"
# Clean up the PID file on exit even if uvicorn crashes.
trap 'rm -f "$PID_FILE"; echo; echo "monitor stopped"' EXIT INT TERM

# `exec` replaces the bash process with uvicorn so signals (Ctrl-C, kill) hit
# the python interpreter directly — clean shutdown, no orphaned process.
exec uv run monitor/server.py --port "$PORT"
