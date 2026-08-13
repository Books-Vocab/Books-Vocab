from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from ops.ios_ui_run_many import RunManyError, classify_bundle, deduplicate_methods, load_methods


def test_load_and_deduplicate_shared_selector(tmp_path: Path) -> None:
    methods = tmp_path / "methods.json"
    methods.write_text(
        json.dumps(
            {
                "runs": [
                    {"clusterID": "reader-runtime", "requirementID": "P4", "selector": "ReaderTests/testOne", "datasetID": "marketing_demo"},
                    {"clusterID": "reader-runtime", "requirementID": "P5", "selector": "ReaderTests/testOne", "datasetID": "marketing_demo"},
                ]
            }
        ),
        encoding="utf-8",
    )
    loaded = load_methods(methods)
    grouped = deduplicate_methods(loaded)
    assert grouped == [
        {
            "selector": "ReaderTests/testOne",
            "datasetID": "marketing_demo",
            "requirementIDs": ["P4", "P5"],
            "clusterIDs": ["reader-runtime"],
        }
    ]


def test_load_rejects_non_exact_selector(tmp_path: Path) -> None:
    methods = tmp_path / "methods.json"
    methods.write_text(
        json.dumps({"runs": [{"clusterID": "x", "requirementID": "P1", "selector": "--grep x", "datasetID": "marketing_demo"}]}),
        encoding="utf-8",
    )
    with pytest.raises(RunManyError, match="exact XCTest selector"):
        load_methods(methods)


def test_classify_bundle_requires_contract(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    (bundle / "artifacts").mkdir(parents=True)
    (bundle / "verdict.json").write_text(json.dumps({"status": "ok", "exit": "0"}), encoding="utf-8")
    assert classify_bundle(bundle, 0) == "failed_contract"
    (bundle / "artifacts" / "ui-evidence-contract.json").write_text(json.dumps({"valid": True}), encoding="utf-8")
    assert classify_bundle(bundle, 0) == "passed_unattested"
