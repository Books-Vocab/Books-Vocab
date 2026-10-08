"""env-check verdicts: missing keys and unsafe App Store fallback flags (#2315)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))
sys.path.insert(0, str(OPS.parent / "backend" / "src"))

import env_drift  # noqa: E402
from kg.settings import _env_truthy  # noqa: E402

FLAGS = (
    "APP_STORE_ALLOW_UNSIGNED_SYNC",
    "APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS",
)

# Spellings the backend itself reads as truthy / falsy (no quote or comment handling).
PLAIN_VALUES = [
    "1", "true", "TRUE", "True", "yes", "YES", "Yes", " true ", "0", "false",
    "no", "", "2", "on", "truee",
]  # fmt: skip

# docker compose strips quotes and inline comments before the backend sees the
# value, so ops must treat these as the truthy value they decode to.
COMPOSE_DECORATED = ['"true"', "'1'", "true ", "true # comment", '"yes" # x', "True"]


@pytest.mark.parametrize("flag", FLAGS)
@pytest.mark.parametrize("raw", COMPOSE_DECORATED)
def test_decorated_truthy_spellings_are_unsafe(flag: str, raw: str) -> None:
    _, unsafe = env_drift.check_env_text(f"{flag}={raw}\n", [], FLAGS)
    assert unsafe == [flag]


@pytest.mark.parametrize("raw", PLAIN_VALUES)
def test_unsafe_verdict_matches_backend_env_truthy(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_STORE_ALLOW_UNSIGNED_SYNC", raw)
    _, unsafe = env_drift.check_env_text(
        f"APP_STORE_ALLOW_UNSIGNED_SYNC={raw}\n", [], FLAGS
    )
    assert bool(unsafe) == _env_truthy("APP_STORE_ALLOW_UNSIGNED_SYNC")


def test_empty_required_value_is_missing() -> None:
    text = "JWT_SECRET=\nADMIN_TOKEN=   \nGEMINI_API_KEY=x\n"
    missing, unsafe = env_drift.check_env_text(
        text, ["JWT_SECRET", "ADMIN_TOKEN", "GEMINI_API_KEY", "ABSENT"], FLAGS
    )
    assert missing == ["JWT_SECRET", "ADMIN_TOKEN", "ABSENT"]
    assert unsafe == []


def _run_cli(stdin: str, *keys: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(OPS / "env_drift.py"), "env-check", *keys],
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exits_nonzero_on_unsafe_flag() -> None:
    proc = _run_cli("JWT_SECRET=x\nAPP_STORE_ALLOW_UNSIGNED_SYNC=True\n", "JWT_SECRET")
    assert proc.returncode != 0
    assert "✓ JWT_SECRET" in proc.stdout
    assert "✗ APP_STORE_ALLOW_UNSIGNED_SYNC" in proc.stdout


def test_cli_ok_and_missing_shape() -> None:
    ok = _run_cli("JWT_SECRET=x\n", "JWT_SECRET")
    assert ok.returncode == 0
    assert "✓ JWT_SECRET" in ok.stdout
    bad = _run_cli("JWT_SECRET=\n", "JWT_SECRET")
    assert bad.returncode != 0
    assert "✗ JWT_SECRET (缺少)" in bad.stdout
