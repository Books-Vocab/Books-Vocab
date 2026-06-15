from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "capability_matrix.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("capability_matrix", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_json_schema_exposes_tiers_and_surfaces(capsys):
    mod = _load_module()

    rc = mod.main(["--json"])
    assert rc == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "kg.capability_matrix.v1"
    assert payload["summary"]["tiers"] >= 4
    assert payload["summary"]["surfaces"] >= 10
    assert any(
        surface["key"] == "devops.safe.ops_edit"
        and surface["minimumTier"] == "production-capable"
        and surface["sideEffect"] == "prod-write"
        for surface in payload["surfaces"]
    )
    assert any(
        surface["key"] == "devops.safe.status"
        and surface["minimumTier"] == "observer"
        and surface["sideEffect"] == "prod-read"
        for surface in payload["surfaces"]
    )
    assert any(
        surface["key"] == "ios.ops.archive-upload"
        and surface["minimumTier"] == "production-capable"
        and "external-upload" in surface["sideEffect"]
        for surface in payload["surfaces"]
    )
    assert any(
        surface["key"] == "ios.ops.catalog"
        and "--dataset <name>" in surface["command"]
        and "UI World" in surface["purpose"]
        for surface in payload["surfaces"]
    )
    required_router_surfaces = {
        "docs.impact",
        "docs.lint.gate",
        "docs.registry.coverage",
        "release.status",
        "release.publish",
        "podcast.ops.status",
        "podcast.ops.reconcile",
        "llm_eval.cli",
    }
    exposed = {surface["key"] for surface in payload["surfaces"]}
    assert required_router_surfaces <= exposed


def test_tier_filter_only_returns_requested_tier(capsys):
    mod = _load_module()

    rc = mod.main(["--json", "--tier", "observer"])
    assert rc == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["filter"]["tier"] == "observer"
    assert payload["summary"]["surfaces"] > 0
    assert all(surface["minimumTier"] == "observer" for surface in payload["surfaces"])


def test_text_output_mentions_contract_summary(capsys):
    mod = _load_module()

    rc = mod.main([])
    assert rc == 0

    out = capsys.readouterr().out
    assert "[capability][tier] observer" in out
    assert "[capability][surface] devops.safe.run-exception" in out
    assert "minimumTier=production-capable" in out
