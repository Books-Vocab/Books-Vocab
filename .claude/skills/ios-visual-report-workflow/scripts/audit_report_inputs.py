#!/usr/bin/env -S uv run --python 3.13 python
"""Read-only audit for the active P3-P15 four-cluster evidence control plane."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


REQUIREMENTS = {f"P{i}" for i in range(3, 16)}


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--report-dir", required=True, type=Path)
    parser.add_argument("--clusters", required=True, type=Path)
    parser.add_argument("--matrix", required=True, type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    report = (root / args.report_dir).resolve()
    clusters_path = (root / args.clusters).resolve()
    matrix_path = (root / args.matrix).resolve()
    problems: list[str] = []
    pngs = {f"p{i}.PNG" for i in range(3, 16)}
    present = {path.name for path in report.iterdir()} if report.is_dir() else set()
    missing_pngs = sorted(pngs - present, key=lambda value: int(re.search(r"\d+", value)[0]))
    if not report.is_dir():
        problems.append(f"report directory missing: {report}")
    if not (report / "IOS2.0.1+7-UI-review-report.pdf").is_file():
        problems.append("report PDF missing: IOS2.0.1+7-UI-review-report.pdf")
    if missing_pngs:
        problems.append(f"missing report images: {missing_pngs}")

    try:
        cluster_doc = load(clusters_path)
    except (OSError, json.JSONDecodeError) as error:
        cluster_doc = {}
        problems.append(f"cannot read cluster manifest: {error}")
    try:
        matrix_doc = load(matrix_path)
    except (OSError, json.JSONDecodeError) as error:
        matrix_doc = {}
        problems.append(f"cannot read matrix: {error}")

    clusters = cluster_doc.get("clusters") if isinstance(cluster_doc, dict) else None
    cluster_ids: list[str] = []
    mapped: list[str] = []
    selectors: list[str] = []
    selector_requirements: list[str] = []
    if not isinstance(clusters, list):
        problems.append("clusters must be a list")
        clusters = []
    for index, cluster in enumerate(clusters):
        if not isinstance(cluster, dict):
            problems.append(f"clusters[{index}] must be an object")
            continue
        cluster_id = cluster.get("id")
        if not isinstance(cluster_id, str) or not cluster_id.strip():
            problems.append(f"clusters[{index}].id missing")
        else:
            cluster_ids.append(cluster_id)
        requirements = cluster.get("requirements")
        if not isinstance(requirements, list):
            problems.append(f"clusters[{index}].requirements must be a list")
            requirements = []
        mapped.extend(value for value in requirements if isinstance(value, str))
        runs = cluster.get("runPlan") or cluster.get("runs") or cluster.get("selectors") or []
        if not isinstance(runs, list):
            problems.append(f"clusters[{index}].runPlan must be a list")
            runs = []
        for run_index, run in enumerate(runs):
            if not isinstance(run, dict):
                problems.append(f"clusters[{index}].runs[{run_index}] must be an object")
                continue
            selector = run.get("selector")
            requirement_id = run.get("requirementID")
            if requirement_id not in REQUIREMENTS:
                problems.append(f"invalid requirementID at clusters[{index}].runPlan[{run_index}]")
            else:
                selector_requirements.append(requirement_id)
            if not isinstance(selector, str) or not re.fullmatch(
                r"[A-Za-z_][A-Za-z0-9_]*/test[A-Za-z0-9_]+", selector
            ):
                problems.append(f"invalid exact selector at clusters[{index}].runs[{run_index}]")
            else:
                selectors.append(selector)

    if len(clusters) != 4:
        problems.append(f"expected exactly 4 clusters, got {len(clusters)}")
    if len(cluster_ids) != len(set(cluster_ids)):
        problems.append("cluster IDs are not unique")
    if set(mapped) != REQUIREMENTS or len(mapped) != len(REQUIREMENTS):
        problems.append(f"requirements must map P3-P15 exactly once; got {sorted(mapped)}")
    if set(selector_requirements) != REQUIREMENTS:
        problems.append(
            "runPlan must provide at least one exact selector for every requirement; "
            f"got {sorted(set(selector_requirements))}"
        )

    matrix_requirements = matrix_doc.get("requirements") if isinstance(matrix_doc, dict) else None
    matrix_ids = {
        item.get("id")
        for item in matrix_requirements or []
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    if matrix_ids != REQUIREMENTS:
        problems.append(f"matrix requirements must be P3-P15; got {sorted(matrix_ids)}")

    result = {
        "schema": "kg.ios.visual-report-input-audit.v1",
        "valid": not problems,
        "reportDir": str(report),
        "pdf": (report / "IOS2.0.1+7-UI-review-report.pdf").is_file(),
        "images": {"expected": 13, "present": len(pngs - set(missing_pngs)), "missing": missing_pngs},
        "clusters": {"count": len(clusters), "ids": cluster_ids, "requirements": sorted(set(mapped))},
        "selectorCount": len(selectors),
        "matrixRequirementCount": len(matrix_ids),
        "problems": problems,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
