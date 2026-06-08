from __future__ import annotations

import json
from pathlib import Path

from catalog_canvas_renderer import render_canvas_html


def write_review_outputs(root: Path, manifest: dict) -> None:
    (root / "review_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (root / "catalog.html").write_text(render_canvas_html(manifest), encoding="utf-8")
