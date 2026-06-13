from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPS = ROOT / "ops"


def _load():
    if str(OPS) not in sys.path:
        sys.path.insert(0, str(OPS))
    spec = importlib.util.spec_from_file_location(
        "uitest_flow_matrix", ROOT / "ops" / "uitest_flow_matrix.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_build_variants_crosses_profiles_and_data():
    mod = _load()

    variants = mod.build_variants(
        profiles=["ui-smoke", "standard"],
        datasets=["marketing_demo"],
        dataset_files=[],
        include_default_data=True,
    )

    assert [variant.label for variant in variants] == [
        "profile:ui-smoke",
        "profile:standard",
        "dataset:marketing_demo+profile:ui-smoke",
        "dataset:marketing_demo+profile:standard",
    ]


def test_dry_run_json_emits_ios_ops_commands(capsys):
    mod = _load()

    rc = mod.main(
        [
            "--file",
            "FixtureDatasetUITests.swift",
            "--profile",
            "standard",
            "--dataset",
            "marketing_demo",
            "--include-default-data",
            "--lease",
            "--dry-run",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "kg.ios.uitest-flow-matrix.v1"
    assert payload["summary"]["total"] == 2
    assert [run["variantId"] for run in payload["runs"]] == [
        "profile:standard",
        "dataset:marketing_demo+profile:standard",
    ]
    for run in payload["runs"]:
        command = run["command"]
        assert command[1:5] == ["test", "--ui", "--file", "FixtureDatasetUITests.swift"]
        assert "--ui-launch-profile" in command
        assert "--lease" in command
        assert command[-1] == "--json"
    assert "--dataset" not in payload["runs"][0]["command"]
    assert payload["runs"][1]["command"][5:9] == [
        "--dataset",
        "marketing_demo",
        "--ui-launch-profile",
        "standard",
    ]
