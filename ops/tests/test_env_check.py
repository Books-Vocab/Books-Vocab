"""env-check verdicts: missing keys and unsafe App Store fallback flags (#2315)."""

from __future__ import annotations

import os
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
    verdict = env_drift.check_env_text(f"{flag}={raw}\n", [], FLAGS)
    assert verdict.unsafe == [flag]
    assert verdict.undecodable == {}


@pytest.mark.parametrize("raw", PLAIN_VALUES)
def test_unsafe_verdict_matches_backend_env_truthy(
    raw: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_STORE_ALLOW_UNSIGNED_SYNC", raw)
    verdict = env_drift.check_env_text(
        f"APP_STORE_ALLOW_UNSIGNED_SYNC={raw}\n", [], FLAGS
    )
    assert verdict.undecodable == {}
    assert bool(verdict.unsafe) == _env_truthy("APP_STORE_ALLOW_UNSIGNED_SYNC")


def test_empty_required_value_is_missing() -> None:
    text = "REQUIRED_KEY=\nADMIN_TOKEN=   \nGEMINI_API_KEY=x\n"
    verdict = env_drift.check_env_text(
        text, ["REQUIRED_KEY", "ADMIN_TOKEN", "GEMINI_API_KEY", "ABSENT"], FLAGS
    )
    assert verdict.missing == ["REQUIRED_KEY", "ADMIN_TOKEN", "ABSENT"]
    assert verdict.unsafe == []
    assert verdict.undecodable == {}


# env-check also enforces the backend's startup rules (JWT_SECRET, LLM provider keys;
# see test_env_check_backend_rules.py).  These tests are about key/flag/decoding
# verdicts, so every CLI run gets a startup-valid baseline prepended; the body under
# test comes after it and so still sees (and may override) any key it defines.
VALID_BASELINE = (
    "JWT_SECRET=fixture-jwt-secret-0123456789-abcdefghij\n"
    "GEMINI_API_KEY=fixture-gemini-key\n"
)


def _run_cli(
    stdin: str, *keys: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(OPS / "env_drift.py"), "env-check", *keys],
        input=VALID_BASELINE + stdin,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_cli_exits_nonzero_on_unsafe_flag() -> None:
    proc = _run_cli(
        "REQUIRED_KEY=x\nAPP_STORE_ALLOW_UNSIGNED_SYNC=True\n", "REQUIRED_KEY"
    )
    assert proc.returncode != 0
    assert "✓ REQUIRED_KEY" in proc.stdout
    assert "✗ APP_STORE_ALLOW_UNSIGNED_SYNC" in proc.stdout


def test_cli_ok_and_missing_shape() -> None:
    ok = _run_cli("REQUIRED_KEY=x\n", "REQUIRED_KEY")
    assert ok.returncode == 0
    assert "✓ REQUIRED_KEY" in ok.stdout
    bad = _run_cli("REQUIRED_KEY=\n", "REQUIRED_KEY")
    assert bad.returncode != 0
    assert "✗ REQUIRED_KEY (缺少)" in bad.stdout


# --- Compose env_file decoding (review of #2610) ---------------------------------
# env-check must judge the value docker compose hands the container, not the raw
# token.  Quote, interpolation and escape expectations were cross-checked against
# `docker compose config` (Compose v2.40.3).  Where Compose versions disagree
# (`KEY= # note`) the pinned verdict is the conservative one.  Every verdict goes
# through the CLI so the exit status the deploy gate consumes is what is asserted.

SYNC = "APP_STORE_ALLOW_UNSIGNED_SYNC"
SECRET_TOKEN = "s3cr3tv4lue"  # a decode failure must never echo the value


def _verdict(
    stdin: str, *keys: str, **process_env: str
) -> subprocess.CompletedProcess[str]:
    return _run_cli(
        stdin, *keys, env={"PATH": os.environ.get("PATH", ""), **process_env}
    )


@pytest.mark.parametrize(
    "body",
    [
        'REQUIRED_KEY=""',
        "REQUIRED_KEY=''",
        'REQUIRED_KEY=  ""  ',
        "REQUIRED_KEY= # disabled",
        'REQUIRED_KEY="" # disabled',
        "REQUIRED_KEY=${SRC:-}",
        "SRC=\nREQUIRED_KEY=${SRC}",
        "SRC=\nREQUIRED_KEY=$SRC",
        "SRC=\nREQUIRED_KEY=${SRC-fallback}",
    ],
)
def test_required_value_that_decodes_to_empty_is_missing(body: str) -> None:
    proc = _verdict(body + "\n", "REQUIRED_KEY")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "✗ REQUIRED_KEY (缺少)" in proc.stdout


@pytest.mark.parametrize(
    ("body", "process_env"),
    [
        ('REQUIRED_KEY="abc"', {}),
        ('REQUIRED_KEY="abc" # note', {}),
        ("REQUIRED_KEY='${NOT_EXPANDED}'", {}),
        ("REQUIRED_KEY=abc#frag", {}),
        ("REQUIRED_KEY=#abc", {}),
        ("REQUIRED_KEY=a$$b", {}),
        ("REQUIRED_KEY=${SRC:-fallback}", {}),
        ("REQUIRED_KEY=${SRC-fallback}", {}),
        ("SRC=\nREQUIRED_KEY=${SRC:-fallback}", {}),
        ("SRC=abc\nREQUIRED_KEY=${SRC}", {}),
        ('SRC=abc\nREQUIRED_KEY="${SRC}-x"', {}),
        ("REQUIRED_KEY=$SRC", {"SRC": "abc"}),
        ("REQUIRED_KEY=${SRC}", {"SRC": "abc"}),
        ("SRC=abc\nREQUIRED_KEY=${SRC}", {"SRC": "abc"}),
        ("REQUIRED_KEY=http://host:8000/a=b", {}),
    ],
)
def test_required_value_that_decodes_non_empty_passes(
    body: str, process_env: dict[str, str]
) -> None:
    proc = _verdict(body + "\n", "REQUIRED_KEY", **process_env)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "✓ REQUIRED_KEY" in proc.stdout


@pytest.mark.parametrize("flag", (SYNC, "APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS"))
@pytest.mark.parametrize(
    ("body", "process_env"),
    [
        ("@FLAG@=${ALLOW_UNSAFE:-true}", {}),
        ("@FLAG@=${ALLOW_UNSAFE-true}", {}),
        ('@FLAG@="${ALLOW_UNSAFE:-yes}"', {}),
        ("@FLAG@=${ALLOW_UNSAFE:-1} # reviewed", {}),
        ("ALLOW_UNSAFE=\n@FLAG@=${ALLOW_UNSAFE:-true}", {}),
        ("ALLOW_UNSAFE=true\n@FLAG@=${ALLOW_UNSAFE}", {}),
        ("ALLOW_UNSAFE=TRUE\n@FLAG@=$ALLOW_UNSAFE", {}),
        ("@FLAG@=$ALLOW_UNSAFE", {"ALLOW_UNSAFE": "1"}),
        ("@FLAG@=${ALLOW_UNSAFE}", {"ALLOW_UNSAFE": "yes"}),
    ],
)
def test_interpolated_unsafe_flag_is_flagged(
    flag: str, body: str, process_env: dict[str, str]
) -> None:
    text = "REQUIRED_KEY=x\n" + body.replace("@FLAG@", flag) + "\n"
    proc = _verdict(text, "REQUIRED_KEY", **process_env)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert f"✗ {flag} (production 不可啟用)" in proc.stdout


@pytest.mark.parametrize(
    "body",
    [
        "@FLAG@=${ALLOW_UNSAFE:-false}",
        "@FLAG@='${ALLOW_UNSAFE:-true}'",
        "@FLAG@=${ALLOW_UNSAFE-}",
        "ALLOW_UNSAFE=\n@FLAG@=${ALLOW_UNSAFE-true}",
        "ALLOW_UNSAFE=false\n@FLAG@=${ALLOW_UNSAFE:-true}",
    ],
)
def test_interpolated_flag_that_decodes_falsy_passes(body: str) -> None:
    text = "REQUIRED_KEY=x\n" + body.replace("@FLAG@", SYNC) + "\n"
    proc = _verdict(text, "REQUIRED_KEY")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert f"✓ {SYNC}" in proc.stdout


@pytest.mark.parametrize(
    ("body", "process_env"),
    [
        ("ADMIN_TOKEN=${X:?err}", {}),
        ("ADMIN_TOKEN=${X:+alt}", {}),
        ("ADMIN_TOKEN=${X:-${Y}}", {}),
        ("ADMIN_TOKEN=${X:-d", {}),
        ("ADMIN_TOKEN=${X}", {}),
        ("ADMIN_TOKEN=$X", {}),
        (f"ADMIN_TOKEN={SECRET_TOKEN}$1x", {}),
        (f'ADMIN_TOKEN="{SECRET_TOKEN}', {}),
        (f'ADMIN_TOKEN="{SECRET_TOKEN}\\nx"', {}),
        (f'ADMIN_TOKEN="a" {SECRET_TOKEN}', {}),
        (f"ADMIN_TOKEN=${{LATER}}\nLATER={SECRET_TOKEN}", {}),
        (f"SRC={SECRET_TOKEN}\nADMIN_TOKEN=${{SRC}}", {"SRC": "other"}),
    ],
)
def test_undecodable_required_value_fails_closed(
    body: str, process_env: dict[str, str]
) -> None:
    proc = _verdict(body + "\n", "ADMIN_TOKEN", **process_env)
    assert proc.returncode == 1, proc.stdout + proc.stderr
    line = next(ln for ln in proc.stdout.splitlines() if "ADMIN_TOKEN" in ln)
    assert line.startswith("✗ ADMIN_TOKEN (無法解析"), proc.stdout
    assert "ADMIN_TOKEN" in proc.stderr
    assert SECRET_TOKEN not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "value", ["${X:?err}", "${X:-${Y}}", "${UNDEFINED_SRC}", '"true', "$"]
)
def test_undecodable_unsafe_flag_value_fails_closed(value: str) -> None:
    proc = _verdict(f"REQUIRED_KEY=x\n{SYNC}={value}\n", "REQUIRED_KEY")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert f"✗ {SYNC} (無法解析" in proc.stdout
    assert SYNC in proc.stderr


def test_undecodable_key_does_not_hide_other_verdicts() -> None:
    proc = _verdict(
        "REQUIRED_KEY=x\nADMIN_TOKEN=${X:?err}\nGEMINI_API_KEY=\n",
        "REQUIRED_KEY",
        "ADMIN_TOKEN",
        "GEMINI_API_KEY",
    )
    assert proc.returncode == 1
    assert "✓ REQUIRED_KEY" in proc.stdout
    assert "✗ ADMIN_TOKEN (無法解析" in proc.stdout
    assert "✗ GEMINI_API_KEY (缺少)" in proc.stdout


# Spellings Compose accepts for `KEY=value` (all become KEY="true" in
# `docker compose config`): optional `export`, spaces around the key, `:` as the
# separator.  The first `=` or `:` splits key from value.
KEY_SPELLINGS = [
    "export {k}={v}",
    "export   {k}  =  {v}",
    "{k} = {v}",
    "{k}: {v}",
    "{k}:{v}",
    "export {k}: {v}",
]


@pytest.mark.parametrize("flag", (SYNC, "APP_STORE_ALLOW_UNSIGNED_NOTIFICATIONS"))
@pytest.mark.parametrize("spelling", KEY_SPELLINGS)
@pytest.mark.parametrize("value", ["true", '"yes"'])
def test_alternate_key_spellings_still_flag_unsafe(
    flag: str, spelling: str, value: str
) -> None:
    text = "REQUIRED_KEY=x\n" + spelling.format(k=flag, v=value) + "\n"
    proc = _verdict(text, "REQUIRED_KEY")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert f"✗ {flag} (production 不可啟用)" in proc.stdout


@pytest.mark.parametrize("spelling", KEY_SPELLINGS)
def test_alternate_key_spellings_satisfy_required(spelling: str) -> None:
    proc = _verdict(spelling.format(k="REQUIRED_KEY", v="x") + "\n", "REQUIRED_KEY")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "✓ REQUIRED_KEY" in proc.stdout


@pytest.mark.parametrize("spelling", KEY_SPELLINGS)
def test_alternate_key_spellings_with_empty_value_are_missing(spelling: str) -> None:
    proc = _verdict(spelling.format(k="REQUIRED_KEY", v="") + "\n", "REQUIRED_KEY")
    assert proc.returncode == 1
    assert "✗ REQUIRED_KEY (缺少)" in proc.stdout


@pytest.mark.parametrize("line", ["REQUIRED_KEY=a:b=c", "REQUIRED_KEY: a=b:c"])
def test_first_separator_splits_key_from_value(line: str) -> None:
    proc = _verdict(line + "\n", "REQUIRED_KEY")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "✓ REQUIRED_KEY" in proc.stdout


@pytest.mark.parametrize("line", ["@K@", "export @K@", "   @K@   "])
def test_bare_key_line_for_unsafe_flag_fails_closed(line: str) -> None:
    # A bare `KEY` line makes Compose read the value from the host's own process
    # env, which env-check cannot observe.
    text = "REQUIRED_KEY=x\n" + line.replace("@K@", SYNC) + "\n"
    proc = _verdict(text, "REQUIRED_KEY", **{SYNC: "true"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert f"✗ {SYNC} (無法解析" in proc.stdout


def test_bare_key_line_for_required_key_fails_closed() -> None:
    proc = _verdict("REQUIRED_KEY\n", "REQUIRED_KEY", REQUIRED_KEY="from-local-env")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "✗ REQUIRED_KEY (無法解析" in proc.stdout


def test_env_drift_parse_keeps_raw_keys() -> None:
    # env-drift compares raw text between two hosts; the Compose key spellings are
    # an env-check concern only and must not change what drift keys on.
    assert env_drift.parse_env_text("export A=1\nB = 2\nC: 3\n") == {
        "export A": "1",
        "B ": " 2",
    }
