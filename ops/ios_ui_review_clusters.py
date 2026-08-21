#!/usr/bin/env -S uv run --python 3.13 python
"""Validate and expand the four-cluster iOS UI review orchestration manifest."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCHEMA = "kg.ios.ui-review-clusters.v1"
REQUIREMENTS = {f"P{n}" for n in range(3, 16)}
CLUSTERS = {
    "reader-runtime",
    "explore-overview",
    "vocabulary-review-card",
    "settings-sync",
}
STATUSES = {"pending", "in_progress", "blocked", "verified"}
SELECTOR_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]+/[A-Za-z][A-Za-z0-9_]+$")
DATASET_RE = re.compile(r"^[A-Za-z0-9._-]+$")


class ClusterManifestError(ValueError):
    pass


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ClusterManifestError(f"cannot read {label}: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ClusterManifestError(f"{label} must be a JSON object")
    return value


def resolve_inside(root: Path, value: str, label: str) -> Path:
    path = (root / value).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise ClusterManifestError(f"{label} escapes repository root: {value}") from error
    return path


def matrix_requirements(matrix: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if matrix.get("schema") != "kg.ios.ui-review-matrix.v1":
        raise ClusterManifestError("matrix schema must be kg.ios.ui-review-matrix.v1")
    raw = matrix.get("requirements")
    if not isinstance(raw, list):
        raise ClusterManifestError("matrix.requirements must be a list")
    result: dict[str, dict[str, Any]] = {}
    seen_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ClusterManifestError("matrix requirements must have string ids")
        requirement_id = item["id"]
        if requirement_id in seen_ids:
            raise ClusterManifestError(f"duplicate requirement id: {requirement_id}")
        seen_ids.add(requirement_id)
        result[requirement_id] = item
    if set(result) != REQUIREMENTS:
        raise ClusterManifestError("matrix must contain exactly P3 through P15")
    return result


def validate(manifest_path: Path, root: Path) -> dict[str, Any]:
    manifest = load_json(manifest_path, "cluster manifest")
    if manifest.get("schema") != SCHEMA:
        raise ClusterManifestError(f"cluster manifest schema must be {SCHEMA}")
    matrix_path = resolve_inside(root, str(manifest.get("matrix", "")), "matrix")
    matrix = load_json(matrix_path, "matrix")
    requirements = matrix_requirements(matrix)
    if manifest.get("defaultDatasetID") and not DATASET_RE.fullmatch(str(manifest["defaultDatasetID"])):
        raise ClusterManifestError("defaultDatasetID is unsafe")
    policy = manifest.get("batchPolicy")
    if not isinstance(policy, dict) or policy.get("buildOnce") is not True or policy.get("runMany") is not True:
        raise ClusterManifestError("batchPolicy must require buildOnce=true and runMany=true")
    raw_clusters = manifest.get("clusters")
    if not isinstance(raw_clusters, list) or len(raw_clusters) != 4:
        raise ClusterManifestError("manifest must contain exactly four clusters")
    seen_requirements: set[str] = set()
    selector_owners: dict[str, tuple[str, str]] = {}
    cluster_results: list[dict[str, Any]] = []
    for cluster in raw_clusters:
        if not isinstance(cluster, dict):
            raise ClusterManifestError("each cluster must be an object")
        cluster_id = cluster.get("id")
        if cluster_id not in CLUSTERS:
            raise ClusterManifestError(f"unknown cluster id: {cluster_id!r}")
        cluster_requirements = cluster.get("requirements")
        if not isinstance(cluster_requirements, list) or not cluster_requirements:
            raise ClusterManifestError(f"{cluster_id}.requirements must be non-empty")
        if any(value not in REQUIREMENTS for value in cluster_requirements):
            raise ClusterManifestError(f"{cluster_id}.requirements contains unknown requirement")
        overlap = seen_requirements.intersection(cluster_requirements)
        if overlap:
            raise ClusterManifestError(f"requirements assigned to multiple clusters: {sorted(overlap)}")
        seen_requirements.update(cluster_requirements)
        source_modules = cluster.get("sourceModules")
        if not isinstance(source_modules, list) or not source_modules:
            raise ClusterManifestError(f"{cluster_id}.sourceModules must be non-empty")
        missing = [value for value in source_modules if not isinstance(value, str) or not resolve_inside(root, value, f"{cluster_id}.sourceModules").is_file()]
        if missing:
            raise ClusterManifestError(f"{cluster_id}.sourceModules missing: {missing}")
        for field in ("acceptanceRefs", "visualStateRefs"):
            refs = cluster.get(field)
            if not isinstance(refs, dict) or set(refs) != set(cluster_requirements):
                raise ClusterManifestError(f"{cluster_id}.{field} must cover every cluster requirement")
        run_plan = cluster.get("runPlan")
        if not isinstance(run_plan, list) or not run_plan:
            raise ClusterManifestError(f"{cluster_id}.runPlan must be non-empty")
        planned_requirements: set[str] = set()
        for run in run_plan:
            if not isinstance(run, dict) or run.get("requirementID") not in cluster_requirements:
                raise ClusterManifestError(f"{cluster_id}.runPlan has an invalid requirementID")
            requirement_id = run["requirementID"]
            planned_requirements.add(requirement_id)
            status = run.get("status")
            if status not in STATUSES:
                raise ClusterManifestError(f"{cluster_id}/{requirement_id} has invalid status")
            dataset_id = run.get("datasetID") or manifest.get("defaultDatasetID")
            if not isinstance(dataset_id, str) or not DATASET_RE.fullmatch(dataset_id):
                raise ClusterManifestError(f"{cluster_id}/{requirement_id} has invalid datasetID")
            selector = run.get("selector")
            if selector is not None:
                if not isinstance(selector, str) or not SELECTOR_RE.fullmatch(selector):
                    raise ClusterManifestError(f"{cluster_id}/{requirement_id} has invalid selector: {selector!r}")
                owner = selector_owners.get(selector)
                if owner is not None:
                    previous_cluster, previous_requirement = owner
                    if previous_cluster != cluster_id:
                        raise ClusterManifestError(
                            f"selector is shared across clusters: {selector} "
                            f"({previous_cluster}/{previous_requirement}, {cluster_id}/{requirement_id})"
                        )
                    if previous_requirement == requirement_id:
                        raise ClusterManifestError(
                            f"selector is duplicated for one requirement: {selector} ({cluster_id}/{requirement_id})"
                        )
                else:
                    selector_owners[selector] = (cluster_id, requirement_id)
        if planned_requirements != set(cluster_requirements):
            raise ClusterManifestError(f"{cluster_id}.runPlan must cover every cluster requirement")
        cluster_results.append({"id": cluster_id, "requirements": cluster_requirements, "runCount": len(run_plan)})
    if seen_requirements != REQUIREMENTS:
        raise ClusterManifestError(f"cluster partition must cover P3-P15; missing={sorted(REQUIREMENTS - seen_requirements)}")
    if {cluster["id"] for cluster in cluster_results} != CLUSTERS:
        raise ClusterManifestError("cluster ids must be the canonical four-cluster set")
    return {
        "schema": SCHEMA,
        "valid": True,
        "clusterCount": len(cluster_results),
        "requirementCount": len(seen_requirements),
        "selectorCount": len(selector_owners),
        "clusters": cluster_results,
        "matrix": str(matrix_path),
    }


def expand_run_plan(manifest_path: Path, root: Path, cluster_id: str | None) -> list[dict[str, Any]]:
    validate(manifest_path, root)
    manifest = load_json(manifest_path, "cluster manifest")
    result: list[dict[str, Any]] = []
    for cluster in manifest["clusters"]:
        if cluster_id and cluster["id"] != cluster_id:
            continue
        for run in cluster["runPlan"]:
            if run.get("selector") is None or run.get("status") in {"pending", "blocked"}:
                continue
            result.append({
                "clusterID": cluster["id"],
                "requirementID": run["requirementID"],
                "selector": run["selector"],
                "datasetID": run.get("datasetID") or manifest.get("defaultDatasetID"),
                "status": run["status"],
            })
    if cluster_id and not any(cluster["id"] == cluster_id for cluster in manifest["clusters"]):
        raise ClusterManifestError(f"unknown cluster id: {cluster_id}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "expand-run-plan"])
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--cluster")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            result: Any = validate(args.manifest, args.root)
        else:
            result = expand_run_plan(args.manifest, args.root, args.cluster)
        payload = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(payload, encoding="utf-8")
        else:
            print(payload, end="")
        return 0
    except (OSError, ClusterManifestError) as error:
        print(json.dumps({"schema": SCHEMA, "valid": False, "error": str(error)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
