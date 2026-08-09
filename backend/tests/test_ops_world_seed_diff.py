"""Strict two-way ``world-diff`` checks for ``kg.seed_spec.v1``."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ops_helpers import run_ops_cli as _cli
from ops_helpers import run_ops_edit as _edit


def _mk_user(dd: Path, uid: str = "demo") -> str:
    result = _edit(str(dd), "user-create", uid, "--commit", "--json")
    assert result.returncode == 0, result.stderr
    return uid


def _seed(dd: Path, uid: str, spec: dict, *extra: str):
    digest = hashlib.sha1(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:8]
    path = dd / f"spec-{digest}.json"
    path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return _edit(str(dd), "seed", uid, str(path), *extra)


def _export_to(dd: Path, uid: str, path: Path) -> None:
    result = _cli(str(dd), "world-export", uid, "--out", str(path))
    assert result.returncode == 0, result.stderr


def _world_diff(dd: Path, uid: str, spec_path: Path) -> dict:
    result = _cli(str(dd), "world-diff", uid, str(spec_path), "--json")
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _base_spec() -> dict:
    return {
        "notebooks": [{"name": "Alpha", "color": "#112233", "sort_order": 2}],
        "cards": [
            {"content": "meticulous", "meaning": "一絲不苟的", "notebook": "Alpha"},
            {"content": "wince", "meaning": "畏縮", "notebook": "Alpha"},
        ],
    }


def test_world_diff_accepts_seed_spec_schema(tmp_path):
    uid = _mk_user(tmp_path)
    assert _seed(tmp_path, uid, _base_spec(), "--commit", "--json").returncode == 0
    exported = tmp_path / "export.json"
    _export_to(tmp_path, uid, exported)

    payload = _world_diff(tmp_path, uid, exported)

    assert payload["schema"] == "kg.ops_world_diff.v1"
    assert payload["mode"] == "seed-spec"
    assert payload["ok"] is True
    assert payload["mismatches"] == []


def test_seed_spec_diff_reports_unexpected_card(tmp_path):
    uid = _mk_user(tmp_path)
    assert _seed(tmp_path, uid, _base_spec(), "--commit", "--json").returncode == 0
    exported = tmp_path / "export.json"
    _export_to(tmp_path, uid, exported)

    # The old expectation path is subset-only and reports this false-green.
    extra = _edit(
        str(tmp_path), "card-add", uid, "meticulous", "--meaning", "一絲不苟的", "--commit"
    )
    assert extra.returncode == 0, extra.stderr

    payload = _world_diff(tmp_path, uid, exported)

    assert payload["ok"] is False
    assert any(
        mismatch["kind"] == "unexpected-card" and "meticulous" in mismatch["path"]
        for mismatch in payload["mismatches"]
    )


def test_seed_spec_diff_reports_unexpected_notebook(tmp_path):
    uid = _mk_user(tmp_path)
    assert _seed(tmp_path, uid, _base_spec(), "--commit", "--json").returncode == 0
    exported = tmp_path / "export.json"
    _export_to(tmp_path, uid, exported)

    extra = _edit(str(tmp_path), "notebook-create", uid, "Ghost", "--commit")
    assert extra.returncode == 0, extra.stderr

    payload = _world_diff(tmp_path, uid, exported)

    assert any(
        mismatch["kind"] == "unexpected-notebook" and "Ghost" in mismatch["path"]
        for mismatch in payload["mismatches"]
    )


def test_seed_spec_diff_reports_missing_and_value_mismatch(tmp_path):
    uid = _mk_user(tmp_path)
    assert _seed(tmp_path, uid, _base_spec(), "--commit", "--json").returncode == 0
    exported = tmp_path / "export.json"
    _export_to(tmp_path, uid, exported)
    spec = json.loads(exported.read_text(encoding="utf-8"))
    spec["cards"][0]["meaning"] = "細心的"
    spec["cards"].append(
        {"content": "absent", "meaning": "不存在", "notebook": "Alpha"}
    )
    exported.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    payload = _world_diff(tmp_path, uid, exported)
    mismatches = payload["mismatches"]

    assert any(m["kind"] == "missing-card" for m in mismatches)
    assert any(
        m["kind"] == "value-mismatch"
        and m["path"] == "cards[Alpha/meticulous].meaning"
        for m in mismatches
    )


def test_seed_spec_diff_normalizes_review_datetimes(tmp_path):
    uid = _mk_user(tmp_path)
    spec = {
        "schema": "kg.seed_spec.v1",
        "cards": [
            {
                "content": "anchor",
                "meaning": "錨點",
                "review": {
                    "review_count": 5,
                    "last_reviewed_at": "2026-06-11T00:00:00Z",
                    "next_review_at": "2026-06-13T00:00:00Z",
                },
            }
        ]
    }
    assert _seed(tmp_path, uid, spec, "--commit", "--json").returncode == 0
    spec_path = tmp_path / "counter-spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    payload = _world_diff(tmp_path, uid, spec_path)

    assert payload["ok"] is True


def test_seed_spec_diff_skips_legacy_state_review(tmp_path):
    uid = _mk_user(tmp_path)
    spec = {
        "schema": "kg.seed_spec.v1",
        "cards": [
            {
                "content": "wince",
                "meaning": "畏縮",
                "review": {"state": "due", "interval": 24},
            }
        ]
    }
    assert _seed(tmp_path, uid, spec, "--commit", "--json").returncode == 0
    spec_path = tmp_path / "legacy-spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    payload = _world_diff(tmp_path, uid, spec_path)

    assert payload["ok"] is True
    assert any(item["path"].endswith(".review") for item in payload["unverified"])


def test_default_notebook_not_reported_as_unexpected(tmp_path):
    uid = _mk_user(tmp_path)
    spec = {
        "schema": "kg.seed_spec.v1",
        "notebooks": [{"name": "Alpha"}],
        "cards": [{"content": "meticulous", "meaning": "一絲不苟的", "notebook": "Alpha"}],
    }
    assert _seed(tmp_path, uid, spec, "--commit", "--json").returncode == 0
    spec_path = tmp_path / "partial-spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")

    payload = _world_diff(tmp_path, uid, spec_path)

    assert payload["ok"] is True
    assert not any(m["kind"] == "unexpected-notebook" for m in payload["mismatches"])
    assert any(item["path"] == "notebooks[我的單字本]" for item in payload["unverified"])


def test_expectation_spec_path_is_unchanged(tmp_path):
    uid = _mk_user(tmp_path)
    assert _seed(
        tmp_path,
        uid,
        {"cards": [{"content": "hello", "meaning": "你好"}]},
        "--commit",
        "--json",
    ).returncode == 0
    spec_path = tmp_path / "expectation.json"
    spec_path.write_text(
        json.dumps(
            {
                "schema": "kg.ops_world_expectation.v1",
                "cards": [{"content": "hello", "meaning": "你好"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    payload = _world_diff(tmp_path, uid, spec_path)

    assert payload["schema"] == "kg.ops_world_diff.v1"
    assert "mode" not in payload or payload["mode"] == "expectation"
