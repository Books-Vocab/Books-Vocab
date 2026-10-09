"""env-check enforces the backend's own startup rules (JWT_SECRET, LLM provider keys).

The verdict comes from calling `kg.settings.load_settings` and
`kg.llm.providers.validate_provider_routing` themselves, so these tests pin both
the CLI contract (per-rule lines, exit status, no secret values) and agreement with
the backend validators, so any backend rule change that env-check misses fails CI.
"""

from __future__ import annotations

import io
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "env_check"
sys.path.insert(0, str(OPS))
sys.path.insert(0, str(OPS.parent / "backend" / "src"))

import env_drift
from kg import settings as backend_settings

GOOD_SECRET = "fixture-jwt-secret-0123456789-abcdefghij"


def _check(text: str, *keys: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(OPS / "env_drift.py"), "env-check", *keys],
        input=text,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ.get("PATH", "")},
    )


def _fixture(name: str) -> subprocess.CompletedProcess[str]:
    return _check((FIXTURES / name).read_text(encoding="utf-8"))


def _rule_lines(proc: subprocess.CompletedProcess[str]) -> dict[str, str]:
    """rule name -> mark, from `✓ [rule] ...` / `✗ [rule] ...` stdout lines."""
    marks: dict[str, str] = {}
    for line in proc.stdout.splitlines():
        if line[:1] in {"✓", "✗"} and line[2:3] == "[":
            marks[line[3 : line.index("]")]] = line[0]
    return marks


def test_good_config_passes_every_rule() -> None:
    proc = _fixture("good.env")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    marks = _rule_lines(proc)
    assert marks == {
        "jwt-present": "✓",
        "jwt-not-placeholder": "✓",
        "jwt-min-length": "✓",
        "llm-routing": "✓",
    }
    assert f"JWT_SECRET 長度 {len(GOOD_SECRET)}" in proc.stdout


def test_31_char_secret_fails_min_length_only() -> None:
    proc = _fixture("jwt_31_chars.env")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    marks = _rule_lines(proc)
    assert marks["jwt-min-length"] == "✗"
    assert marks["jwt-present"] == marks["jwt-not-placeholder"] == "✓"
    assert "JWT_SECRET 長度 31，backend 要求 >= 32" in proc.stdout
    assert "x" * 31 not in proc.stdout + proc.stderr


def test_placeholder_secret_fails_not_placeholder_only() -> None:
    proc = _fixture("jwt_placeholder.env")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    marks = _rule_lines(proc)
    assert marks["jwt-not-placeholder"] == "✗"
    assert (
        marks["jwt-min-length"] == "✓"
    )  # long enough: only the placeholder rule trips
    assert "your-secret-key-change-in-production" not in proc.stdout + proc.stderr


def test_missing_secret_fails_present() -> None:
    proc = _fixture("jwt_missing.env")
    assert proc.returncode == 1
    assert _rule_lines(proc)["jwt-present"] == "✗"


def test_deepseek_routed_provider_with_blank_key_fails_routing() -> None:
    proc = _fixture("deepseek_blank_key.env")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    marks = _rule_lines(proc)
    assert marks["llm-routing"] == "✗"
    assert all(mark == "✓" for rule, mark in marks.items() if rule.startswith("jwt-"))
    assert "DEEPSEEK_API_KEY not configured" in proc.stdout
    assert "LLM_PROVIDER_DEFAULT" in proc.stdout
    assert "fixture-gemini-key" not in proc.stdout + proc.stderr


def test_unrouted_provider_may_have_blank_key() -> None:
    text = f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=k\nDEEPSEEK_API_KEY=\n"
    proc = _check(text)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_default_gemini_routing_requires_gemini_key() -> None:
    proc = _check(f"JWT_SECRET={GOOD_SECRET}\n")
    assert proc.returncode == 1
    assert _rule_lines(proc)["llm-routing"] == "✗"
    assert "GEMINI_API_KEY not configured" in proc.stdout


def test_unknown_provider_name_fails_routing() -> None:
    proc = _check(
        f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=k\nLLM_PROVIDER_TRANSLATE=nope\n"
    )
    assert proc.returncode == 1
    assert _rule_lines(proc)["llm-routing"] == "✗"


def test_routing_ignores_the_callers_own_process_env() -> None:
    # A developer shell exporting a routing var / key must not change the verdict
    # about the target .env.
    proc = subprocess.run(
        [sys.executable, str(OPS / "env_drift.py"), "env-check"],
        input=f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=k\n",
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": os.environ.get("PATH", ""),
            "LLM_PROVIDER_DEFAULT": "deepseek",
            "DEEPSEEK_API_KEY": "",
        },
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_undecodable_routing_value_fails_closed() -> None:
    proc = _check(f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=${{X:?err}}\n")
    assert proc.returncode == 1
    assert _rule_lines(proc)["llm-routing"] == "✗"


def test_undecodable_secret_fails_closed_without_echoing_value() -> None:
    proc = _check(
        'JWT_SECRET="abcdefabcdefabcdefabcdefabcdefabcdef\nGEMINI_API_KEY=k\n'
    )
    assert proc.returncode == 1
    assert _rule_lines(proc)["jwt-secret"] == "✗"
    assert "abcdefabcdef" not in proc.stdout + proc.stderr


# --- drift pins: env-check must agree with the backend validators themselves ----

SECRET_CASES = [
    "",
    "x",
    "x" * 31,
    "x" * 32,
    "x" * 33,
    *sorted(backend_settings._JWT_SECRET_PLACEHOLDERS),
    "SECRET",
    "Change-Me",
    "  changeme  ",
    GOOD_SECRET,
    # the 37-char placeholder is long enough: only the placeholder rule rejects it,
    # and only on an exact (strip/lower) match
    "your-secret-key-change-in-production-2",
]


def _backend_accepts(secret: str, monkeypatch: pytest.MonkeyPatch) -> bool:
    for key in list(os.environ):
        monkeypatch.delenv(key)
    if secret:
        monkeypatch.setenv("JWT_SECRET", secret)
    try:
        backend_settings.load_settings()
    except RuntimeError as exc:
        if str(exc).startswith("JWT_SECRET"):
            return False
        raise
    return True


@pytest.mark.parametrize("secret", SECRET_CASES)
def test_jwt_verdict_matches_backend_load_settings(
    secret: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _backend_accepts(secret, monkeypatch)
    results = env_drift.backend_startup_rules(
        f"JWT_SECRET='{secret}'\nGEMINI_API_KEY=k\n", {}
    )
    jwt = [r for r in results if r.rule.startswith("jwt-")]
    assert jwt, results
    assert all(r.ok for r in jwt) is expected, (secret and len(secret), jwt)


def test_jwt_rule_constants_come_from_the_backend() -> None:
    # The rules read the backend's constants at call time: changing them changes
    # the verdict, so a threshold bump in settings.py cannot leave env-check stale.
    text = f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=k\n"
    assert all(r.ok for r in env_drift.backend_startup_rules(text, {}))
    original = backend_settings._JWT_SECRET_MIN_LENGTH
    backend_settings._JWT_SECRET_MIN_LENGTH = len(GOOD_SECRET) + 1
    try:
        failing = [r for r in env_drift.backend_startup_rules(text, {}) if not r.ok]
    finally:
        backend_settings._JWT_SECRET_MIN_LENGTH = original
    assert {r.rule for r in failing} >= {"jwt-min-length"}


def test_rule_disagreement_with_backend_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # If the backend grows a JWT rule env-check does not model, the agreement rule
    # trips rather than silently passing.
    def stricter() -> object:
        raise RuntimeError("JWT_SECRET has a rule env-check does not know")

    monkeypatch.setattr(backend_settings, "load_settings", stricter)
    results = env_drift.backend_startup_rules(
        f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=k\n", {}
    )
    assert any(r.rule == "jwt-backend-agreement" and not r.ok for r in results)


def test_output_never_contains_secret_values() -> None:
    proc = _check(
        f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=fixture-gemini-key-value\n"
        "DEEPSEEK_API_KEY=fixture-deepseek-key-value\n"
    )
    out = proc.stdout + proc.stderr
    for value in (
        GOOD_SECRET,
        "fixture-gemini-key-value",
        "fixture-deepseek-key-value",
    ):
        assert value not in out
    assert "GEMINI_API_KEY 長度 " in out


# --- review hardening: secret hygiene, isolation, import side effects ---------------

SENTINEL = "SUPERSECRETSENTINEL"


def test_routing_exception_text_never_echoes_the_routed_value() -> None:
    proc = _check(
        f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=k\nLLM_PROVIDER_TRANSLATE={SENTINEL}\n"
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _rule_lines(proc)["llm-routing"] == "✗"
    assert SENTINEL not in proc.stdout + proc.stderr


@pytest.mark.parametrize(
    "var", ["EMBEDDING_DIM", "API_RATE_LIMIT", "PRO_DAILY_LIMIT_USD"]
)
def test_backend_logger_output_never_reaches_the_cli_streams(var: str) -> None:
    # kg.settings._env_int/_env_float/_env_rate_limit log `Env var X='value'` plus a
    # traceback through Python's last-resort stderr handler.
    proc = _check(f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=k\n{var}={SENTINEL}\n")
    assert SENTINEL not in proc.stdout + proc.stderr, proc.stdout + proc.stderr
    assert "Env var" not in proc.stderr


def test_log_disabling_is_restored_after_the_run() -> None:
    import logging

    before = logging.root.manager.disable
    env_drift.backend_startup_rules(f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=k\n", {})
    assert logging.root.manager.disable == before


def test_operator_shell_variables_do_not_feed_interpolation() -> None:
    proc = subprocess.run(
        [sys.executable, str(OPS / "env_drift.py"), "env-check"],
        input="JWT_SECRET=${OPERATOR_JWT}\nGEMINI_API_KEY=k\n",
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ.get("PATH", ""), "OPERATOR_JWT": GOOD_SECRET},
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert _rule_lines(proc)["jwt-secret"] == "✗"
    assert GOOD_SECRET not in proc.stdout + proc.stderr


def test_default_environ_is_empty_not_the_process_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPERATOR_JWT", GOOD_SECRET)
    results = env_drift.backend_startup_rules(
        "JWT_SECRET=${OPERATOR_JWT}\nGEMINI_API_KEY=k\n"
    )
    assert any(r.rule == "jwt-secret" and not r.ok for r in results)


def test_run_leaves_no_bytecode_and_no_sys_path_residue(tmp_path: Path) -> None:
    src = tmp_path / "src"
    shutil.copytree(
        OPS.parent / "backend" / "src" / "kg",
        src / "kg",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    script = (
        "import sys, env_drift\n"
        f"env_drift.BACKEND_SRC = __import__('pathlib').Path({str(src)!r})\n"
        "before = list(sys.path); flag = sys.dont_write_bytecode\n"
        f"r = env_drift.backend_startup_rules('JWT_SECRET={GOOD_SECRET}\\nGEMINI_API_KEY=k\\n', {{}})\n"
        "assert all(x.ok for x in r), r\n"
        "assert sys.path == before and sys.dont_write_bytecode == flag\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
        cwd=OPS,
        env={"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(OPS)},
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not list(src.rglob("__pycache__"))


def test_unimportable_backend_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    real_src = str(OPS.parent / "backend" / "src")
    for name in [m for m in sys.modules if m == "kg" or m.startswith("kg.")]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setattr(sys, "path", [p for p in sys.path if p != real_src])
    monkeypatch.setattr(env_drift, "BACKEND_SRC", Path("/nonexistent/backend/src"))
    results = env_drift.backend_startup_rules(f"JWT_SECRET={GOOD_SECRET}\n", {})
    assert [(r.rule, r.ok) for r in results] == [("backend-import", False)]
    assert "ModuleNotFoundError" in results[0].detail


def test_cli_exits_nonzero_when_backend_is_stricter(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def stricter() -> object:
        raise RuntimeError("JWT_SECRET has a rule env-check does not know")

    monkeypatch.setattr(backend_settings, "load_settings", stricter)
    monkeypatch.setattr(
        sys, "stdin", io.StringIO(f"JWT_SECRET={GOOD_SECRET}\nGEMINI_API_KEY=k\n")
    )
    assert env_drift.env_check_main([]) == 1
    assert "✗ [jwt-backend-agreement]" in capsys.readouterr().out


def test_rule_disagreement_fails_closed_when_backend_is_laxer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(backend_settings, "load_settings", lambda: object())
    results = env_drift.backend_startup_rules(
        "JWT_SECRET=short\nGEMINI_API_KEY=k\n", {}
    )
    assert any(r.rule == "jwt-backend-agreement" and not r.ok for r in results)
