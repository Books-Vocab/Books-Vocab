"""Issue #2002: the gate-history source behind ``compute --mode auto``.

Everything here goes through the real history reader/writer; only the clock,
load, probe and transport seams (already seams in production) are faked.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS))

import compute
from lib import compute_history as history
from lib.compute_receipt import ReceiptSigner
from test_compute_cli import (
    _cmd,
    _felix_probe,
    _out,
    _remote_registry,
    _wire_felix,
)

NOW = 2_000_000.0
DAY = 86400.0
PROFILE = "fake.echo"


def _cache(root: Path) -> Path:
    return root / ".cache" / "compute"


def _seed(root: Path, mode: str, durations, *, transfer=None, age=100.0):
    for index, duration in enumerate(durations):
        history.record(
            _cache(root),
            profile=PROFILE,
            mode=mode,
            duration_seconds=duration,
            transfer_seconds=transfer,
            now=NOW - age + index,
        )


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """Routing fixture with the REAL history reader (no ``_gate_history`` stub)."""

    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": True, "head": "a" * 40}
    )
    monkeypatch.setattr(compute, "_available_capabilities", lambda: {"bash"})
    monkeypatch.setattr(compute, "_now", lambda: NOW)
    monkeypatch.setattr(
        compute,
        "_local_load",
        lambda: {"busy": True, "slowdown": 4.0, "host_id": "oscar-host"},
    )
    monkeypatch.setattr(compute.platform, "node", lambda: "oscar-host")
    return tmp_path


def _probe(monkeypatch, **over):
    over.setdefault("observed_at", NOW)
    monkeypatch.setattr(compute, "_probe_felix", lambda *a, **k: _felix_probe(**over))


def _auto_route(env, capsys) -> dict:
    registry = _remote_registry(env, signer=ReceiptSigner.generate())
    assert compute.main(_cmd(env, registry, "plan", "--mode", "auto")) == 0
    return _out(capsys)["result"]["route"]


# ----------------------------------------------------------- reader / writer


def test_record_read_round_trip(tmp_path):
    _seed(tmp_path, "local", [10.0, 12.0, 11.0])
    assert history.local_durations(_cache(tmp_path), PROFILE, NOW) == [10.0, 12.0, 11.0]
    line = (_cache(tmp_path) / history.HISTORY_NAME).read_text().splitlines()[0]
    assert set(json.loads(line)) == {
        "profile",
        "mode",
        "duration_seconds",
        "transfer_seconds",
        "recorded_at",
    }


def test_only_newest_twenty_local_samples_and_other_profiles_excluded(tmp_path):
    _seed(tmp_path, "local", [float(i) for i in range(30)])
    history.record(
        _cache(tmp_path),
        profile="other",
        mode="local",
        duration_seconds=999.0,
        transfer_seconds=None,
        now=NOW - 1,
    )
    samples = history.local_durations(_cache(tmp_path), PROFILE, NOW)
    assert samples == [float(i) for i in range(10, 30)]


def test_malformed_lines_are_ignored_never_raised(tmp_path):
    _seed(tmp_path, "local", [5.0, 6.0, 7.0])
    path = _cache(tmp_path) / history.HISTORY_NAME
    good = '{"profile":"%s","mode":"local","duration_seconds":9.0,"transfer_seconds":null,"recorded_at":%s}'
    bad = [
        "not json",
        "[1, 2]",
        '"str"',
        "null",
        good.replace('"local"', '"remote"') % (PROFILE, NOW - 5),
        good.replace("9.0", "-1") % (PROFILE, NOW - 5),
        good.replace("9.0", "true") % (PROFILE, NOW - 5),
        good.replace("9.0", '"9"') % (PROFILE, NOW - 5),
        good.replace("9.0", "NaN") % (PROFILE, NOW - 5),
        good.replace("9.0", "Infinity") % (PROFILE, NOW - 5),
        good % (PROFILE, NOW + 3600),  # future
        good % ("", NOW - 5),
        good.replace("null", '"x"') % (PROFILE, NOW - 5),
        good.replace("null", "-2") % (PROFILE, NOW - 5),
        "\x00\xff\xfe",
        "[" * 100000,
    ]
    with path.open("ab") as handle:
        for line in bad:
            handle.write(line.encode("utf-8", "surrogateescape") + b"\n")
    assert history.local_durations(_cache(tmp_path), PROFILE, NOW) == [5.0, 6.0, 7.0]
    assert len(history.read_entries(_cache(tmp_path), NOW)) == 3


def test_missing_or_unreadable_history_reads_as_none(tmp_path):
    assert history.local_durations(_cache(tmp_path), PROFILE, NOW) is None
    (_cache(tmp_path) / history.HISTORY_NAME).mkdir(parents=True)  # a directory
    assert history.local_durations(_cache(tmp_path), PROFILE, NOW) is None


def test_compaction_keeps_latest_fifty_per_profile(tmp_path):
    cache = _cache(tmp_path)
    cache.mkdir(parents=True)
    rows = []
    for index in range(1, history.COMPACT_ABOVE_LINES + 1):
        profile = "a" if index % 2 else "b"
        rows.append(
            json.dumps(
                {
                    "profile": profile,
                    "mode": "local",
                    "duration_seconds": float(index),
                    "transfer_seconds": None,
                    "recorded_at": NOW - 10_000 + index,
                }
            )
        )
    (cache / history.HISTORY_NAME).write_text("\n".join(rows) + "\n")
    history.record(
        cache,
        profile="a",
        mode="local",
        duration_seconds=1.0,
        transfer_seconds=None,
        now=NOW,
    )
    entries = history.read_entries(cache, NOW)
    by_profile = {p: [e for e in entries if e["profile"] == p] for p in ("a", "b")}
    assert len(by_profile["a"]) == history.KEEP_PER_PROFILE
    assert len(by_profile["b"]) == history.KEEP_PER_PROFILE
    assert by_profile["a"][-1]["recorded_at"] == NOW  # newest survives
    assert by_profile["b"][-1]["duration_seconds"] == float(history.COMPACT_ABOVE_LINES)
    assert [p.name for p in cache.iterdir() if p.name.startswith(".history-")] == []


def test_history_older_than_fourteen_days_expires(tmp_path):
    _seed(tmp_path, "local", [1.0, 2.0, 3.0], age=14 * DAY - 10)
    assert history.local_durations(_cache(tmp_path), PROFILE, NOW) is not None
    assert history.local_durations(_cache(tmp_path), PROFILE, NOW + 20) is None


def test_fewer_than_three_local_samples_return_none(tmp_path):
    _seed(tmp_path, "local", [1.0, 2.0])
    assert history.local_durations(_cache(tmp_path), PROFILE, NOW) is None
    _seed(tmp_path, "local", [3.0], age=50.0)
    assert history.local_durations(_cache(tmp_path), PROFILE, NOW) is not None


def test_felix_runs_never_count_as_local_samples(tmp_path):
    _seed(tmp_path, "felix", [1.0, 2.0, 3.0, 4.0], transfer=2.0)
    assert history.local_durations(_cache(tmp_path), PROFILE, NOW) is None


def test_felix_transfer_is_median_of_fresh_samples(tmp_path):
    for value, age in ((1.0, 100.0), (9.0, 90.0), (3.0, 80.0), (500.0, 15 * DAY)):
        history.record(
            _cache(tmp_path),
            profile=PROFILE,
            mode="felix",
            duration_seconds=10.0,
            transfer_seconds=value,
            now=NOW - age,
        )
    assert history.felix_transfer_seconds(_cache(tmp_path), PROFILE, NOW) == 3.0
    assert history.felix_transfer_seconds(_cache(tmp_path), "other", NOW) is None


def test_record_rejects_invalid_values_without_touching_the_file(tmp_path):
    for bad in (float("nan"), -1.0, float("inf")):
        with pytest.raises(ValueError):
            history.record(
                _cache(tmp_path),
                profile=PROFILE,
                mode="local",
                duration_seconds=bad,
                transfer_seconds=None,
                now=NOW,
            )
    assert not (_cache(tmp_path) / history.HISTORY_NAME).exists()


# ---------------------------------------------------------- decision matrix


def test_fresh_history_busy_and_positive_savings_selects_felix(
    env, monkeypatch, capsys
):
    _seed(env, "local", [100.0, 110.0, 105.0])
    _probe(monkeypatch)
    route = _auto_route(env, capsys)
    assert route["selected"] == "felix"
    assert route["reason_code"] == "felix-selected-positive-savings"


def test_not_busy_stays_local(env, monkeypatch, capsys):
    _seed(env, "local", [100.0, 110.0, 105.0])
    _probe(monkeypatch)
    monkeypatch.setattr(
        compute, "_local_load", lambda: {"busy": False, "slowdown": 1.0}
    )
    route = _auto_route(env, capsys)
    assert (route["selected"], route["reason_code"]) == (
        "local",
        "auto-local-local-not-busy",
    )


def test_unprofitable_stays_local(env, monkeypatch, capsys):
    _seed(env, "local", [1.0, 1.0, 1.0])
    _probe(monkeypatch)
    monkeypatch.setattr(compute, "_local_load", lambda: {"busy": True, "slowdown": 1.0})
    route = _auto_route(env, capsys)
    assert (route["selected"], route["reason_code"]) == (
        "local",
        "auto-local-no-positive-savings",
    )


def test_no_history_stays_local(env, monkeypatch, capsys):
    _probe(monkeypatch)
    route = _auto_route(env, capsys)
    assert (route["selected"], route["reason_code"]) == (
        "local",
        "auto-local-cost-unknown",
    )


def test_sparse_history_stays_local(env, monkeypatch, capsys):
    _seed(env, "local", [100.0, 110.0])
    _probe(monkeypatch)
    assert _auto_route(env, capsys)["reason_code"] == "auto-local-cost-unknown"


def test_expired_history_stays_local(env, monkeypatch, capsys):
    _seed(env, "local", [100.0, 110.0, 105.0], age=15 * DAY)
    _probe(monkeypatch)
    assert _auto_route(env, capsys)["reason_code"] == "auto-local-cost-unknown"


def test_corrupt_history_stays_local(env, monkeypatch, capsys):
    _cache(env).mkdir(parents=True)
    (_cache(env) / history.HISTORY_NAME).write_text("garbage\n{\n" * 10)
    _probe(monkeypatch)
    assert _auto_route(env, capsys)["reason_code"] == "auto-local-cost-unknown"


def test_missing_felix_transfer_stays_local(env, monkeypatch, capsys):
    _seed(env, "local", [100.0, 110.0, 105.0])
    _probe(monkeypatch, transfer_seconds=None)
    assert _auto_route(env, capsys)["reason_code"] == "auto-local-cost-unknown"


def test_felix_transfer_history_substitutes_for_a_silent_probe(
    env, monkeypatch, capsys
):
    _seed(env, "local", [100.0, 110.0, 105.0])
    _seed(env, "felix", [90.0], transfer=2.0)
    _probe(monkeypatch, transfer_seconds=None)
    route = _auto_route(env, capsys)
    assert route["selected"] == "felix"


def test_plan_and_status_never_write_history(env, monkeypatch, capsys):
    _seed(env, "local", [100.0, 110.0, 105.0])
    _probe(monkeypatch)
    registry = _remote_registry(env, signer=ReceiptSigner.generate())
    path = _cache(env) / history.HISTORY_NAME
    before = path.read_bytes()
    assert compute.main(_cmd(env, registry, "plan", "--mode", "auto")) == 0
    assert (
        compute.main(["--repo", str(env), "--registry", str(registry), "status"]) == 0
    )
    capsys.readouterr()
    assert path.read_bytes() == before


# ------------------------------------------------------------- write timing


def test_successful_local_run_records_a_local_sample(env, monkeypatch, capsys):
    registry = _remote_registry(env, signer=None)
    assert compute.main(_cmd(env, registry, "run")) == 0
    capsys.readouterr()
    entries = history.read_entries(_cache(env), NOW)
    assert len(entries) == 1
    assert entries[0]["profile"] == PROFILE
    assert entries[0]["mode"] == "local"
    assert entries[0]["transfer_seconds"] is None
    assert entries[0]["duration_seconds"] >= 0


def test_failed_local_run_records_nothing(env, monkeypatch, capsys):
    registry = _remote_registry(env, signer=None)

    class Done:
        returncode, stdout, stderr = 1, "", ""

    monkeypatch.setattr(compute.subprocess, "run", lambda *a, **k: Done())
    assert compute.main(_cmd(env, registry, "run")) == 1
    capsys.readouterr()
    assert not (_cache(env) / history.HISTORY_NAME).exists()


def test_refused_run_records_nothing(env, monkeypatch, capsys):
    registry = _remote_registry(env, signer=None)
    monkeypatch.setattr(
        compute, "_git_state", lambda _: {"clean": False, "head": "a" * 40}
    )
    assert compute.main(_cmd(env, registry, "run")) != 0
    capsys.readouterr()
    assert not (_cache(env) / history.HISTORY_NAME).exists()


def test_verified_felix_success_records_duration_and_transfer(env, monkeypatch, capsys):
    signer = ReceiptSigner.generate()
    registry = _remote_registry(env, signer=signer)
    _wire_felix(monkeypatch, signer)
    monkeypatch.setattr(compute, "_now", lambda: 1000.0)  # fake receipt's clock
    assert compute.main(_cmd(env, registry, "run", "--mode", "felix")) == 0
    capsys.readouterr()
    entries = history.read_entries(_cache(env), 1000.0)
    assert [e["mode"] for e in entries] == ["felix"]
    assert entries[0]["duration_seconds"] >= entries[0]["transfer_seconds"] >= 0


def test_felix_remote_failure_and_bad_receipt_record_nothing(env, monkeypatch, capsys):
    signer = ReceiptSigner.generate()
    registry = _remote_registry(env, signer=signer)
    monkeypatch.setattr(compute, "_now", lambda: 1000.0)  # fake receipt's clock
    _wire_felix(monkeypatch, signer, returncode=3)
    assert compute.main(_cmd(env, registry, "run", "--mode", "felix")) == 3
    _wire_felix(monkeypatch, signer, tamper={"nonce": "0" * 32})
    assert compute.main(_cmd(env, registry, "run", "--mode", "felix")) != 0
    capsys.readouterr()
    assert not (_cache(env) / history.HISTORY_NAME).exists()


def test_history_write_failure_does_not_change_run_result(env, monkeypatch, capsys):
    registry = _remote_registry(env, signer=None)
    (env / ".cache").write_text("a file where the cache directory must go")
    assert compute.main(_cmd(env, registry, "run")) == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["ok"] is True
    assert payload["result"]["returncode"] == 0
    assert "history not recorded" in captured.err


def test_unexpected_recorder_error_does_not_change_run_result(env, monkeypatch, capsys):
    registry = _remote_registry(env, signer=None)

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(history, "record", boom)
    assert compute.main(_cmd(env, registry, "run")) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
