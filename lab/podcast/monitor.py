#!/usr/bin/env python3
"""Simple web monitor for podcast pipeline. Auto-refreshes every 3s."""

import http.server
import os
import subprocess
import time
from pathlib import Path

PORT = 8888
WORKSPACE = Path("/Users/chenliangyu/kg/lab/podcast/workspaces/flow_950f1a7d")


def get_status_html():
    now = time.strftime("%H:%M:%S")

    # Log
    log_path = WORKSPACE / "log.md"
    log_content = log_path.read_text() if log_path.exists() else "(no log yet)"

    # Source chapters
    ch_dir = WORKSPACE / "source" / "chapters"
    if ch_dir.exists():
        chapters = sorted(ch_dir.glob("ch_*.md"))
        ch_lines = "\n".join(
            f"  {f.name:20s} {f.stat().st_size:>8,} bytes"
            for f in chapters
        )
    else:
        ch_lines = "(none)"

    # Plan
    overview = WORKSPACE / "plan" / "overview.md"
    plan_lines = []
    if overview.exists():
        plan_lines.append(f'<span class="ok">&#10003; overview.md</span> ({overview.stat().st_size:,} bytes)')
    else:
        plan_lines.append('<span class="pending">○ overview.md</span>')
    ep_dir = WORKSPACE / "plan" / "episodes"
    if ep_dir.exists():
        for f in sorted(ep_dir.glob("ep_*.md")):
            plan_lines.append(f'<span class="ok">&#10003; {f.name}</span> ({f.stat().st_size:,} bytes)')
    plan_html = "\n".join(plan_lines)

    # Scripts
    scripts_dir = WORKSPACE / "scripts"
    script_files = sorted(scripts_dir.glob("ep_*_script.md")) if scripts_dir.exists() else []
    if script_files:
        script_lines = []
        for f in script_files:
            words = len(f.read_text().split())
            mins = round(words / 150)
            script_lines.append(f'<span class="ok">&#10003; {f.name}</span> — {words:,} words (~{mins} min)')
        scripts_html = "\n".join(script_lines)
    else:
        scripts_html = '<span class="pending">○ (no scripts yet)</span>'

    # Running agents
    try:
        result = subprocess.run(
            ["ps", "-eo", "pid,etime,pcpu,pmem,command"],
            capture_output=True, text=True, timeout=5,
        )
        agents = []
        for line in result.stdout.split("\n"):
            if "claude" in line and "opus" in line and "grep" not in line:
                parts = line.split()
                pid, elapsed, cpu, mem = parts[0], parts[1], parts[2], parts[3]
                # Extract label from prompt
                label = "Scriptwriter" if "Scriptwriter" in line else "Agent"
                if "ep_" in line:
                    import re
                    ep_match = re.search(r"ep_(\d+)", line)
                    if ep_match:
                        label = f"Scriptwriter EP{ep_match.group(1)}"
                agents.append(
                    f'<span class="ok">&#9654;</span> {label:20s}  PID {pid}  elapsed {elapsed}  CPU {cpu}%  MEM {mem}%'
                )
        agents_html = "\n".join(agents) if agents else '<span class="pending">idle — no agents running</span>'
    except Exception:
        agents_html = "(error checking)"

    return f"""\
<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="3">
<title>Podcast Pipeline</title>
<style>
body {{ font-family: 'SF Mono', monospace; background: #1a1a2e; color: #e0e0e0; padding: 20px; max-width: 900px; margin: 0 auto; }}
h1 {{ color: #00d4ff; font-size: 1.4em; }}
h2 {{ color: #00d4ff; font-size: 1.1em; margin-top: 25px; }}
pre {{ background: #16213e; padding: 15px; border-radius: 8px; overflow-x: auto; white-space: pre-wrap; font-size: 13px; line-height: 1.5; }}
.ok {{ color: #4caf50; }}
.fail {{ color: #f44336; }}
.pending {{ color: #ffeb3b; }}
.section {{ margin: 15px 0; border-left: 3px solid #00d4ff; padding-left: 15px; }}
.time {{ color: #888; font-size: 0.9em; }}
</style>
</head><body>
<h1>Podcast Pipeline Monitor</h1>
<p class="time">Updated: {now}</p>

<div class="section">
<h2>Running Agents</h2>
<pre>{agents_html}</pre>
</div>

<div class="section">
<h2>Scripts</h2>
<pre>{scripts_html}</pre>
</div>

<div class="section">
<h2>Plan</h2>
<pre>{plan_html}</pre>
</div>

<div class="section">
<h2>Source Chapters ({len(list(ch_dir.glob('ch_*.md'))) if ch_dir.exists() else 0} files)</h2>
<pre>{ch_lines}</pre>
</div>

<div class="section">
<h2>Pipeline Log</h2>
<pre>{log_content}</pre>
</div>

</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(get_status_html().encode())

    def log_message(self, format, *args):
        pass  # suppress request logs


if __name__ == "__main__":
    print(f"Monitor: http://localhost:{PORT}")
    server = http.server.HTTPServer(("", PORT), Handler)
    server.serve_forever()
