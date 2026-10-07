"""The production-image lock check must catch the #2088 drift and nothing else.

The image used to `pip install .` against pyproject.toml ranges, so a rebuild
picked up whatever upstream had released. scripts/check_image_lock.py compares
the image's installed distributions with uv.lock; these tests pin its closure
walk (extras, markers, groups) and its verdicts.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import check_image_lock as lockcheck  # noqa: E402

LOCK = tomllib.loads(
    """
version = 1
revision = 3
requires-python = "==3.13.*"

[[package]]
name = "app"
version = "1.0.0"
source = { editable = "." }
dependencies = [
    { name = "web", extra = ["standard"] },
    { name = "winonly", marker = "sys_platform == 'win32'" },
    { name = "speedups", marker = "platform_machine == 'aarch64' or platform_machine == 'x86_64'" },
]

[package.dev-dependencies]
dev = [
    { name = "pytest" },
]

[[package]]
name = "web"
version = "2.0.0"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "core" },
]

[package.optional-dependencies]
standard = [
    { name = "fastloop" },
]

[[package]]
name = "core"
version = "3.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "fastloop"
version = "0.1.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "winonly"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "speedups"
version = "1.0.0"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pytest"
version = "9.0.3"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "pluggy" },
]

[[package]]
name = "pluggy"
version = "1.6.0"
source = { registry = "https://pypi.org/simple" }
"""
)

LINUX_X86_64 = {
    "implementation_name": "cpython",
    "implementation_version": "3.13.7",
    "os_name": "posix",
    "platform_machine": "x86_64",
    "platform_release": "6.8.0",
    "platform_system": "Linux",
    "platform_version": "#1 SMP",
    "python_full_version": "3.13.7",
    "platform_python_implementation": "CPython",
    "python_version": "3.13",
    "sys_platform": "linux",
}

RUNTIME = {"web": "2.0.0", "core": "3.0.0", "fastloop": "0.1.0", "speedups": "1.0.0"}


def _installed(**overrides: str) -> list[tuple[str, str]]:
    versions = {**RUNTIME, "pip": "25.2", **overrides}
    return [(name, version) for name, version in versions.items() if version]


def test_runtime_closure_follows_extras_and_evaluates_markers_for_the_image() -> None:
    assert lockcheck.locked_closure(LOCK, LINUX_X86_64) == RUNTIME

    riscv = {**LINUX_X86_64, "platform_machine": "riscv64"}
    assert "speedups" not in lockcheck.locked_closure(LOCK, riscv)


def test_dependency_groups_are_only_walked_when_named() -> None:
    with_dev = lockcheck.locked_closure(LOCK, LINUX_X86_64, groups=["dev"])

    assert with_dev == {**RUNTIME, "pytest": "9.0.3", "pluggy": "1.6.0"}
    with pytest.raises(lockcheck.LockError, match="no dependency group 'docs'"):
        lockcheck.locked_closure(LOCK, LINUX_X86_64, groups=["docs"])


def test_image_with_exact_locked_versions_passes() -> None:
    report = lockcheck.compare(RUNTIME, {}, _installed())

    assert report.ok, report


def test_resolve_at_build_time_drift_is_reported() -> None:
    """The #2088 image: newer upstream releases, an unlocked transitive
    dependency, unpinned pytest, and the root project installed as a dist."""
    installed = _installed(web="2.1.0", **{"opentelemetry-api": "1.45.1", "pytest": "9.1.1", "app": "1.0.0"})
    installed.remove(("core", "3.0.0"))

    report = lockcheck.compare(RUNTIME, {}, installed)

    assert not report.ok
    assert report.mismatched == {"web": ("2.0.0", ["2.1.0"])}
    assert report.missing == {"core": "3.0.0"}
    assert report.unexpected == {"app": ["1.0.0"], "opentelemetry-api": ["1.45.1"], "pytest": ["9.1.1"]}


def test_allowed_group_packages_must_still_match_the_lock() -> None:
    allowed = {"pytest": "9.0.3", "pluggy": "1.6.0"}

    assert lockcheck.compare(RUNTIME, allowed, _installed(pytest="9.0.3")).ok
    drifted = lockcheck.compare(RUNTIME, allowed, _installed(pytest="9.1.1"))
    assert drifted.mismatched == {"pytest": ("9.0.3", ["9.1.1"])}


def test_installed_names_are_normalized_and_duplicates_fail() -> None:
    renamed = [("Web", "2.0.0"), ("Core", "3.0.0"), ("fast_loop", "0.1.0"), ("speedups", "1.0.0")]
    lock_closure = {"web": "2.0.0", "core": "3.0.0", "fast-loop": "0.1.0", "speedups": "1.0.0"}
    assert lockcheck.compare(lock_closure, {}, renamed).ok

    report = lockcheck.compare(RUNTIME, {}, [*_installed(), ("web", "2.0.0")])
    assert report.duplicated == {"web": ["2.0.0", "2.0.0"]}
    assert not report.ok


def test_real_lock_runtime_closure_excludes_dev_tooling() -> None:
    lock = tomllib.loads(lockcheck.DEFAULT_LOCK.read_text(encoding="utf-8"))

    runtime = lockcheck.locked_closure(lock, LINUX_X86_64)
    with_dev = lockcheck.locked_closure(lock, LINUX_X86_64, groups=["dev"])

    for name in ("fastapi", "starlette", "uvicorn", "uvloop", "greenlet", "sentry-sdk", "requests"):
        assert name in runtime
    for name in ("pytest", "pytest-asyncio", "pytest-cov", "ruff", "colorama", "kg"):
        assert name not in runtime
    assert {"pytest", "pytest-asyncio", "pytest-cov", "ruff"} <= with_dev.keys()


def _fake_probe(distributions: list[tuple[str, str]]):
    def probe(image: str) -> lockcheck.Probe:
        assert image == "kg-api:test"
        return lockcheck.Probe(environment=dict(LINUX_X86_64), distributions=distributions)

    return probe


def test_main_exit_status_distinguishes_match_drift_and_probe_errors(capsys: pytest.CaptureFixture[str]) -> None:
    lock = tomllib.loads(lockcheck.DEFAULT_LOCK.read_text(encoding="utf-8"))
    runtime = lockcheck.locked_closure(lock, LINUX_X86_64)
    exact = [*runtime.items(), ("pip", "25.2")]
    args = ["--image", "kg-api:test", "--lock", str(lockcheck.DEFAULT_LOCK)]

    assert lockcheck.main(args, probe=_fake_probe(exact)) == 0
    assert "OK kg-api:test" in capsys.readouterr().out

    assert lockcheck.main(args, probe=_fake_probe([*exact, ("pytest", "9.0.3")])) == 1
    assert "unexpected  pytest==9.0.3" in capsys.readouterr().out
    assert lockcheck.main([*args, "--allow-group", "dev"], probe=_fake_probe([*exact, ("pytest", "9.0.3")])) == 0
    capsys.readouterr()

    def broken(image: str) -> lockcheck.Probe:
        raise lockcheck.ProbeError("probe exited 125: no such image")

    assert lockcheck.main(args, probe=broken) == 2
    assert "no such image" in capsys.readouterr().err


def test_probe_output_must_be_the_expected_json() -> None:
    probe = lockcheck.parse_probe('{"environment": {"sys_platform": "linux"}, "distributions": [["pip", "25.2"]]}')
    assert probe.distributions == [("pip", "25.2")]

    with pytest.raises(lockcheck.ProbeError):
        lockcheck.parse_probe("Traceback (most recent call last):")
