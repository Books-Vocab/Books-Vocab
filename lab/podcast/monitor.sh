#!/bin/bash
# Simple web monitor for podcast pipeline
# Usage: ./monitor.sh [port]
PORT=${1:-8888}
WORKSPACE="/Users/chenliangyu/kg/lab/podcast/workspaces/flow_950f1a7d"

echo "Monitoring: $WORKSPACE"
echo "Open: http://localhost:$PORT"

while true; do
  {
    echo "HTTP/1.1 200 OK"
    echo "Content-Type: text/html; charset=utf-8"
    echo "Refresh: 3"
    echo ""
    cat <<'HTML'
<html><head><meta charset="utf-8"><title>Podcast Pipeline</title>
<style>body{font-family:monospace;background:#1a1a2e;color:#e0e0e0;padding:20px;max-width:900px;margin:0 auto}
h2{color:#00d4ff}pre{background:#16213e;padding:15px;border-radius:8px;overflow-x:auto;white-space:pre-wrap;font-size:13px}
.ok{color:#0f0}.fail{color:#f44}.pending{color:#ff0}.section{margin:20px 0;border-left:3px solid #00d4ff;padding-left:15px}</style></head><body>
<h1>🎙️ Podcast Pipeline Monitor</h1>
HTML
    echo "<p>Updated: $(date '+%H:%M:%S')</p>"

    # Log
    echo "<div class='section'><h2>Pipeline Log</h2><pre>"
    if [ -f "$WORKSPACE/log.md" ]; then
      cat "$WORKSPACE/log.md"
    else
      echo "(no log yet)"
    fi
    echo "</pre></div>"

    # Source chapters
    echo "<div class='section'><h2>Source Chapters</h2><pre>"
    if [ -d "$WORKSPACE/source/chapters" ]; then
      ls -lh "$WORKSPACE/source/chapters/" 2>/dev/null | tail -n +2
    else
      echo "(none)"
    fi
    echo "</pre></div>"

    # Plan
    echo "<div class='section'><h2>Plan</h2><pre>"
    [ -f "$WORKSPACE/plan/overview.md" ] && echo "<span class='ok'>✓ overview.md</span> ($(wc -c < "$WORKSPACE/plan/overview.md") bytes)" || echo "<span class='pending'>○ overview.md</span>"
    for f in "$WORKSPACE/plan/episodes/"ep_*.md; do
      [ -f "$f" ] && echo "<span class='ok'>✓ $(basename $f)</span> ($(wc -c < "$f") bytes)"
    done 2>/dev/null
    echo "</pre></div>"

    # Scripts
    echo "<div class='section'><h2>Scripts</h2><pre>"
    if ls "$WORKSPACE/scripts/"ep_*_script.md 1>/dev/null 2>&1; then
      for f in "$WORKSPACE/scripts/"ep_*_script.md; do
        words=$(wc -w < "$f" | tr -d ' ')
        echo "<span class='ok'>✓ $(basename $f)</span> — ${words} words"
      done
    else
      echo "<span class='pending'>○ (no scripts yet)</span>"
    fi
    echo "</pre></div>"

    # Running processes
    echo "<div class='section'><h2>Running Agents</h2><pre>"
    ps aux | grep "claude.*opus" | grep -v grep || echo "(none)"
    echo "</pre></div>"

    echo "</body></html>"
  } | nc -l $PORT -w 1 2>/dev/null
done
