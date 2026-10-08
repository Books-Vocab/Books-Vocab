"""renderLogs must escape every log field (issue #2301)."""

from __future__ import annotations

import re
from pathlib import Path

HTML = Path(__file__).resolve().parents[1] / "src" / "kg" / "admin_dashboard.html"


def _render_logs_body() -> str:
    src = HTML.read_text(encoding="utf-8")
    start = src.index("function renderLogs()")
    end = src.index("\n}\n", start)
    return src[start:end]


def test_render_logs_escapes_every_interpolated_field():
    body = _render_logs_body()
    template = body[body.index("box.innerHTML = [...rows]") :]
    interpolations = re.findall(r"\$\{([^`{}]*(?:\{[^{}]*\}[^`{}]*)*)\}", template)
    field_exprs = [e for e in interpolations if re.search(r"\br\.(ts|level|name|request_id|msg)\b", e)]
    assert field_exprs, "no log field interpolations found"
    for expr in field_exprs:
        assert expr.strip().startswith("escapeHtml("), f"unescaped interpolation: ${{{expr}}}"
    for field in ("ts", "level", "name", "request_id", "msg"):
        assert any(f"r.{field}" in e for e in field_exprs), f"r.{field} not rendered/escaped"


def test_render_logs_has_no_ad_hoc_escape():
    assert "replace(/</g" not in _render_logs_body()
