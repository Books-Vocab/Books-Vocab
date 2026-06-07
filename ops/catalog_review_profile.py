from __future__ import annotations

import json
from pathlib import Path


def load_profile(path: Path) -> dict:
    profile = json.loads(path.read_text(encoding="utf-8"))
    profile["_path"] = str(path)
    return profile
