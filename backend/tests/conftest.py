from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

# Always prefer this workspace's source tree during tests.
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Force deterministic test env (do not inherit prod secrets/config).
os.environ["KG_DATA_DIR"] = "/tmp/kg_test_default"
os.environ["JWT_SECRET"] = "test-secret-key-for-ci-at-least-32-bytes"
os.environ["GEMINI_API_KEY"] = "fake-key"
