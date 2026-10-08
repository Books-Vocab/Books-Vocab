"""Every ops/launchd/*.plist is the versioned source of a deployed job (#2071).

com.butler.kg-disk-guard.plist was named by no other file, was reported as a
dead leftover, and is in fact loaded on felix (~/Library/LaunchAgents,
StartInterval 300, last exit 0) — deleting it would have dropped the only
copy of that job's definition. An undocumented manifest is indistinguishable
from a dead one, so each must be named by at least one other tracked file that
says where it is installed, and carry a Label matching its filename (the name
`launchctl print gui/<uid>/<label>` and the docs use).

The Label is read with a regex, not plistlib: launchd's CFPropertyList parser
accepts the `--` inside the XML comments of com.kg.reconcile / com.kg.uisweep
(`plutil -lint` OK), strict expat does not.

    uv run --no-project --python 3.13 --with pytest pytest -q ops/tests/test_launchd_manifests.py
"""

from __future__ import annotations

import plistlib
import re
import subprocess
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_MANIFESTS = sorted((_ROOT / "ops" / "launchd").glob("*.plist"))
_LABEL_RE = re.compile(r"<key>Label</key>\s*<string>([^<]+)</string>")


def test_manifest_directory_is_found():
    assert _MANIFESTS, "positive control: no manifests under ops/launchd/"


@pytest.mark.parametrize("manifest", _MANIFESTS, ids=lambda p: p.name)
def test_manifest_label_matches_filename(manifest):
    labels = _LABEL_RE.findall(manifest.read_text(encoding="utf-8"))
    assert labels == [manifest.stem]


@pytest.mark.parametrize("manifest", _MANIFESTS, ids=lambda p: p.name)
def test_manifest_is_documented_elsewhere(manifest):
    rel = manifest.relative_to(_ROOT).as_posix()
    this_test = Path(__file__).resolve().relative_to(_ROOT).as_posix()  # names it above
    hits = subprocess.run(
        ["git", "-C", str(_ROOT), "grep", "-l", "--fixed-strings", manifest.name]
        + ["--", ".", f":(exclude){rel}", f":(exclude){this_test}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert hits.returncode in (0, 1), hits.stderr
    assert hits.stdout.split(), (
        f"{rel} is named by no other tracked file — document where it is installed "
        "(docs/reference/host_topology.md) or delete it"
    )


# ── com.kg.log-retention: the only scheduler of kg.log_retention (#2091) ──
#
# Before it existed the log DBs were pruned only by the manual admin endpoint,
# so they grew without limit. Each assertion below is a way the job can be
# loaded, exit, and never prune: launchd itself reports nothing either way.

_LOG_RETENTION = _ROOT / "ops" / "launchd" / "com.kg.log-retention.plist"
_BACKUP = _ROOT / "ops" / "launchd" / "com.kg.backup.plist"
_COMPOSE = _ROOT / "backend" / "docker-compose.yml"
_CONTAINER_RE = re.compile(r"^\s*container_name:\s*(\S+)\s*$", re.MULTILINE)


def _load(manifest: Path) -> dict:
    """plistlib (strict expat) is safe here: these two manifests keep `--` out of their comments."""
    assert manifest.is_file(), f"{manifest.relative_to(_ROOT)} is missing"
    with manifest.open("rb") as fh:
        return plistlib.load(fh)


def test_log_retention_runs_the_pruner_for_every_db_inside_the_api_container():
    # Production Python exists only inside the compose container (KG_DATA_DIR,
    # *_RETENTION_DAYS, appuser), so the job is `docker exec`, never host
    # Python. A stale container name, a renamed module or a missing --all (the
    # CLI then prints help and exits 2) fails every night. The CLI flags are
    # covered by backend/tests/test_log_retention.py.
    containers = _CONTAINER_RE.findall(_COMPOSE.read_text(encoding="utf-8"))
    assert len(containers) == 1, containers
    assert _load(_LOG_RETENTION)["ProgramArguments"] == [
        "/usr/bin/env",
        "docker",
        "exec",
        containers[0],
        "python",
        "-m",
        "kg.log_retention",
        "--all",
        "--json",
    ]
    # `-m kg.log_retention` resolves against the image's PYTHONPATH=/app/src.
    assert (_ROOT / "backend" / "src" / "kg" / "log_retention.py").is_file()


def test_log_retention_resolves_docker_like_the_reconciler():
    # launchd starts with a bare PATH; OrbStack installs the docker CLI here.
    path = _load(_LOG_RETENTION)["EnvironmentVariables"]["PATH"].split(":")
    assert "/Users/chenliangyu/.orbstack/bin" in path


def test_log_retention_is_a_daily_one_shot_away_from_the_backup():
    job = _load(_LOG_RETENTION)
    schedule = job["StartCalendarInterval"]
    assert sorted(schedule) == ["Hour", "Minute"], "Hour+Minute only = once a day"
    # The backup tars the same live SQLite files; a mass DELETE in the same
    # hour risks a torn copy.
    assert schedule["Hour"] != _load(_BACKUP)["StartCalendarInterval"]["Hour"]
    assert job["RunAtLoad"] is False, (
        "the first (largest) prune must wait for the off-peak slot"
    )
    assert "KeepAlive" not in job, "one-shot: KeepAlive would re-run it in a loop"


def test_log_retention_keeps_its_report():
    job = _load(_LOG_RETENTION)
    assert (
        job["StandardOutPath"]
        == "/Users/chenliangyu/Library/Logs/kg_log_retention.out.log"
    )
    assert (
        job["StandardErrorPath"]
        == "/Users/chenliangyu/Library/Logs/kg_log_retention.err.log"
    )
