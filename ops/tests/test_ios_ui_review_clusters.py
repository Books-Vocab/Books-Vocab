from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ops.ios_ui_review_clusters import CLUSTERS, REQUIREMENTS, expand_run_plan, validate


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "ops" / "fixtures" / "ios_ui_review_clusters.json"


def test_cluster_manifest_partitions_all_fifteen_requirements() -> None:
    result = validate(MANIFEST, ROOT)

    assert result["valid"] is True
    assert result["clusterCount"] == 5
    assert result["requirementCount"] == len(REQUIREMENTS)
    assert {cluster["id"] for cluster in result["clusters"]} == CLUSTERS


def test_expand_run_plan_emits_only_executable_exact_selectors() -> None:
    runs = expand_run_plan(MANIFEST, ROOT, "settings-sync")

    assert runs
    assert all("/" in run["selector"] for run in runs)
    assert all(run["requirementID"] in {"P14", "P15"} for run in runs)
    assert all(run["datasetID"] == "marketing_demo" for run in runs)
    assert not any(run["selector"] is None for run in runs)


def test_manifest_is_machine_readable() -> None:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))

    assert raw["schema"] == "kg.ios.ui-review-clusters.v1"
    assert raw["batchPolicy"] == {
        "buildOnce": True,
        "runMany": True,
        "oneEvidenceBundlePerSelector": True,
        "oneSourceHeadPerBatch": True,
    }
