#!/usr/bin/env bash
# Start or restart the podcast pipeline monitor dashboard.
#
# Usage:
#   ./start.sh              # start or restart on port 8765
#   ./start.sh 9000         # use custom port
#   ./start.sh --stop       # just kill any running instance
#
# Idempotent: if a server is already running on the same port, it's killed
# cleanly before a new one starts. Logs go to monitor.log in this directory.

set -euo pipefail

cd "$(dirname "$0")"

PORT="${1:-8765}"
LOG="monitor.log"
PID_FILE=".monitor.pid"

kill_existing() {
  # Kill by PID file if present
  if [[ -f "$PID_FILE" ]]; then
    local pid
    pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      echo "→ stopping monitor (pid $pid)"
      kill "$pid" 2>/dev/null || true
      # Wait up to 3s for graceful exit
      for _ in 1 2 3 4 5 6; do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
      kill -9 "$pid" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
  fi

  # Kill anything still bound to the port (belt-and-suspenders)
  local port_pids
  port_pids="$(lsof -t -i ":$PORT" 2>/dev/null || true)"
  if [[ -n "$port_pids" ]]; then
    echo "→ port $PORT was occupied by pid(s): $port_pids — killing"
    kill $port_pids 2>/dev/null || true
    sleep 1
    kill -9 $port_pids 2>/dev/null || true
  fi
}

if [[ "${1:-}" == "--stop" ]]; then
  kill_existing
  echo "monitor stopped"
  exit 0
fi

kill_existing

echo "→ starting monitor on port $PORT"
nohup uv run monitor/server.py --port "$PORT" > "$LOG" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"

# Wait for readiness
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
