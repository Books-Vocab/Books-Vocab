"""Contract tests for the toolchain-free ``ui_graph`` query path."""
from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
from pathlib import Path

OPS = Path(__file__).resolve().parent.parent
ROOT = OPS.parent
CLI = OPS / "ui_graph.py"
CONTRACT = OPS / "tests" / "fixtures" / "ticket_factory_contracts" / "IMP-20260813-4c0ad1.json"

_spec = importlib.util.spec_from_file_location("ui_graph", CLI)
ui_graph = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(ui_graph)


def test_type_query_refuses_implicit_build_and_reports_missing_index(tmp_path):
    marker = tmp_path / "build-delegate-called"
    fake_build = tmp_path / "fake-ios-build.sh"
    fake_build.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' called > \"$KG_UI_GRAPH_TEST_MARKER\"\n"
        "exit 97\n",
        encoding="utf-8",
    )
    fake_build.chmod(fake_build.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env["KG_IOS_BUILD_DELEGATE"] = str(fake_build)
    env["KG_UI_GRAPH_TEST_MARKER"] = str(marker)
    result = subprocess.run(
        [str(CLI), "--type", "SettingsStatusValue", "--json"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == "kg.ui.graph.v1"
    assert payload["status"] == "refused"
    assert payload["reason"] == "missing-index"
    assert payload["query"] == {"type": "SettingsStatusValue", "surface": None}
    assert not marker.exists(), result.stderr


def test_explicit_build_is_the_only_build_path(monkeypatch, capsys):
    calls = []

    def fake_acquire(source_root, kinds, **kwargs):
        calls.append((source_root, kinds, kwargs))
        return {"sourceRoot": source_root, "symbols": []}, source_root

    monkeypatch.setattr(ui_graph.kgindex_records, "acquire", fake_acquire)

    assert ui_graph.main(["--build", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "kg.ui.graph.v1"
    assert payload["nodeCount"] == 0
    assert calls == [("ios/BooksAndVocab/", ("struct", "class"), {
        "records_json": None,
        "store_path": None,
        "label": "ui_graph",
    })]


def test_contract_manifest_is_verified_and_bounded():
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert payload["ticket_id"] == "IMP-20260813-4c0ad1"
    assert payload["status"] == "verified"
    assert payload["spawned_processes"] == []
    assert isinstance(payload["verdict"], str) and payload["verdict"]
    assert isinstance(payload["exact_head"], str) and payload["exact_head"]
    assert isinstance(payload["evidence_path"], str) and payload["evidence_path"]
