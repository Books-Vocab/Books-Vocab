#!/usr/bin/env bash
set -euo pipefail

SERVER="${SERVER:-ubuntu@13.193.212.134}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/lightsail_default.pem}"
SSH_OPTS=( -T -i "$SSH_KEY" -o StrictHostKeyChecking=accept-new -o BatchMode=yes )

run_remote() {
  ssh "${SSH_OPTS[@]}" "$SERVER" "$@"
}

echo "== Host =="
run_remote "hostname; uptime"

echo ""
echo "== Caddy =="
run_remote "sudo systemctl is-active caddy || true"
run_remote "sudo sed -n '1,120p' /etc/caddy/Caddyfile"

echo ""
echo "== Docker Containers =="
run_remote "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"

echo ""
echo "== Local Health Checks on Host =="
run_remote "for u in http://127.0.0.1:8000/docs; do code=\$(curl -s -o /dev/null -w '%{http_code}' \"\$u\" || true); echo \"\$u -> \$code\"; done"
