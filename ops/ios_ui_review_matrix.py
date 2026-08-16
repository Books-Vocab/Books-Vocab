#!/usr/bin/env -S uv run --python 3.13 python
"""Validate the executable coverage matrix for the historical iOS UI report.

The report images are reference material, not a test plan. This matrix makes
the missing bridge explicit: every image needs a fixture, a selector, runtime
steps, visual checks, and at least one counterexample before it can be called
verified. Pending rows are valid during a multi-day convergence wave; strict
completion is intentionally fail-closed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Any

from uitest_evidence_contract import validate_bundle
from uitest_review_attest import evidence_root_sha256 as _evidence_root_sha256
from ui_world_manifest import FIXTURE_DOMAIN_IDS


SCHEMA = "kg.ios.ui-review-matrix.v1"
REQUIRED_IDS = tuple(f"P{index}" for index in range(1, 16))
STATUSES = {"pending", "in_progress", "verified", "blocked"}
EXACT_METHOD_SELECTOR = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\/test[A-Za-z0-9_]+$")
SAFE_DATASET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class UIReviewMatrixError(ValueError):
    pass


def _mapping(value: Any, *, owner: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UIReviewMatrixError(f"{owner} must be an object")
    return value


def _non_empty_strings(value: Any, *, owner: str, minimum: int = 1) -> list[str]:
    if not isinstance(value, list) or len(value) < minimum:
        raise UIReviewMatrixError(f"{owner} must contain at least {minimum} items")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise UIReviewMatrixError(f"{owner} must contain non-empty strings")
    return value


def _non_empty_string(value: Any, *, owner: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UIReviewMatrixError(f"{owner} must be a non-empty string")
    return value


def _unique_non_empty_strings(value: Any, *, owner: str, minimum: int = 1) -> list[str]:
    values = _non_empty_strings(value, owner=owner, minimum=minimum)
    if len(values) != len(set(values)):
        raise UIReviewMatrixError(f"{owner} must not contain duplicate labels")
    return values


def _canonical_selector(value: Any, *, owner: str) -> str:
    """Normalize an optional method transport flag to an exact XCTest method."""
    selector = _non_empty_string(value, owner=owner).strip()
    if selector.startswith("--file ") or selector.startswith("--grep "):
        raise UIReviewMatrixError(f"{owner} must be an exact ClassName/testMethodName selector")
    if selector.startswith("--method "):
        selector = selector[len("--method ") :].strip()
    if not EXACT_METHOD_SELECTOR.fullmatch(selector):
        raise UIReviewMatrixError(
            f"{owner} must be an exact ClassName/testMethodName selector: {selector!r}"
        )
    return selector


def _load_json(path: Path, *, owner: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UIReviewMatrixError(f"cannot read {owner} {path}: {error}") from error
    return _mapping(value, owner=owner)


def _resolve_rooted_path(value: str, *, root: Path, owner: str) -> tuple[Path, str]:
    relative = Path(value)
    if relative.is_absolute():
        resolved = relative.resolve()
        try:
            stored = resolved.relative_to(root.resolve()).as_posix()
        except ValueError as error:
            raise UIReviewMatrixError(f"{owner} must be inside repository root: {value}") from error
    else:
        if ".." in relative.parts:
            raise UIReviewMatrixError(f"{owner} must not escape repository root: {value}")
        resolved = (root / relative).resolve()
        stored = relative.as_posix()
        try:
            resolved.relative_to(root.resolve())
        except ValueError as error:
            raise UIReviewMatrixError(f"{owner} resolves outside repository root: {value}") from error
    return resolved, stored


def _dataset_path_for_id(*, root: Path, dataset_id: str) -> Path:
    if not SAFE_DATASET_ID.fullmatch(dataset_id):
        raise UIReviewMatrixError(f"unsafe UI World dataset id: {dataset_id!r}")
    dataset_directory = (root / "ops" / "fixtures" / "ui_worlds").resolve()
    try:
        dataset_directory.relative_to(root.resolve())
    except ValueError as error:
        raise UIReviewMatrixError(
            "UI World dataset directory resolves outside repository root"
        ) from error
    dataset_path = (dataset_directory / f"{dataset_id}.json").resolve()
    try:
        dataset_path.relative_to(dataset_directory)
    except ValueError as error:
        raise UIReviewMatrixError(f"UI World dataset path escapes repository root: {dataset_id!r}") from error
    if not dataset_path.is_file():
        raise UIReviewMatrixError(f"UI World dataset {dataset_id} file does not exist")
    return dataset_path


def _fixture_ids_for_dataset(*, root: Path, dataset_id: str) -> set[str]:
    dataset_path = _dataset_path_for_id(root=root, dataset_id=dataset_id)
    _validate_ui_world_dataset(dataset_path, label=f"UI World dataset {dataset_id}")
    dataset = _load_json(dataset_path, owner=f"UI World dataset {dataset_id}")
    if dataset.get("datasetID") != dataset_id:
        raise UIReviewMatrixError(
            f"UI World dataset filename/id mismatch: requested {dataset_id!r}, "
            f"manifest has {dataset.get('datasetID')!r}"
        )
    fixture_ids: set[str] = set()
    for domain in FIXTURE_DOMAIN_IDS:
        raw_fixtures = dataset.get(domain)
        if not isinstance(raw_fixtures, dict):
            continue
        for fixture_id in raw_fixtures:
            fixture_ids.add(fixture_id)
            fixture_ids.add(f"{domain}.{fixture_id}")

    # Canonical cross-domain evidence is declared under scenarioContext rather
    # than a seed domain.  These rows are still fixture contracts: dictionary
    # rows are consumed by FixtureDatasetStore and surface-contract rows are
    # the portable state/asset mapping used by the UI evidence flows.  Keep
    # both the declared ID and a qualified surface alias so matrix authors do
    # not have to guess which namespace a contract uses.
    scenario_context = dataset.get("scenarioContext")
    if isinstance(scenario_context, dict):
        dictionary = scenario_context.get("dictionary")
        if isinstance(dictionary, dict):
            lookup = dictionary.get("lookup")
            if isinstance(lookup, dict):
                for row in lookup.values():
                    if isinstance(row, dict) and isinstance(row.get("fixtureID"), str):
                        fixture_ids.add(row["fixtureID"])
                        fixture_ids.add(f"dictionary.{row['fixtureID']}")
            coverage = dictionary.get("coverage")
            if isinstance(coverage, dict):
                for group in coverage.values():
                    if not isinstance(group, dict):
                        continue
                    raw_ids = group.get("fixtureIDs")
                    if not isinstance(raw_ids, list):
                        continue
                    for fixture_id in raw_ids:
                        if isinstance(fixture_id, str):
                            fixture_ids.add(fixture_id)
                            fixture_ids.add(f"dictionary.{fixture_id}")

        contracts = scenario_context.get("surfaceContracts")
        if isinstance(contracts, dict):
            for surface, contract in contracts.items():
                if not isinstance(contract, dict):
                    continue
                rows = []
                for group in ("required", "counterexamples"):
                    raw_rows = contract.get(group)
                    if isinstance(raw_rows, list):
                        rows.extend(raw_rows)
                for row in rows:
                    if not isinstance(row, dict) or not isinstance(row.get("fixtureID"), str):
                        continue
                    fixture_id = row["fixtureID"]
                    fixture_ids.add(fixture_id)
                    fixture_ids.add(f"{surface}.{fixture_id}")
    return fixture_ids


def _require_fixture_ids(
    requirement: dict[str, Any],
    *,
    root: Path,
    dataset_id: str,
) -> None:
    available = _fixture_ids_for_dataset(root=root, dataset_id=dataset_id)
    required = _non_empty_strings(
        requirement.get("requiredFixtureIDs"),
        owner=f"{requirement.get('id')}.requiredFixtureIDs",
    )
    missing = sorted(set(required) - available)
    if missing:
        raise UIReviewMatrixError(
            f"required fixture IDs are not declared by UI World {dataset_id}: {missing}"
        )


def _git_head(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip() or None


def _git_source_tree_dirty(root: Path) -> bool | None:
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return bool(result.stdout.strip())


def _git_source_commit_matches_current_or_matrix_receipt(
    root: Path,
    source_commit: Any,
) -> bool:
    """Accept source HEAD or a committed matrix-only receipt after it.

    Evidence is produced against a clean source snapshot.  ``record-many`` then
    writes the tracked matrix, so a later validation HEAD can legitimately differ
    without changing the source tree that produced the evidence. Keep this
    exception narrow: the source must be an ancestor of HEAD and every
    non-matrix path must remain identical. Report receipts are updated before
    evidence is run and therefore cannot hide post-evidence source drift.
    """
    if not isinstance(source_commit, str) or not source_commit.strip():
        return False
    source_commit = source_commit.strip()
    current_head = _git_head(root)
    if current_head is None:
        return False
    if source_commit == current_head:
        return True

    try:
        subprocess.run(
            ["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_commit, current_head],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
        non_receipt_diff = subprocess.run(
            [
                "git",
                "diff",
                "--quiet",
                source_commit,
                current_head,
                "--",
                ".",
                ":(exclude)ops/fixtures/ios_ui_review_matrix.json",
            ],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return False
    return non_receipt_diff.returncode == 0


def _validate_ui_world_dataset(path: Path, *, label: str) -> None:
    manifest_script = Path(__file__).with_name("ui_world_manifest.py")
    try:
        result = subprocess.run(
            [sys.executable, str(manifest_script), "validate", str(path), "--label", label],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise UIReviewMatrixError(f"cannot execute UI World validator: {error}") from error
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise UIReviewMatrixError(f"UI World {label} failed manifest validation: {detail}")


def _evidence_provenance(
    evidence_root: Path,
    *,
    requirement: dict[str, Any],
    selector: str,
    dataset_id: str,
    run_id: str,
    repository_root: Path | None = None,
    validate_steps: bool = True,
) -> dict[str, Any]:
    """Require one complete, already-attested retained run before recording verified.

    The runner and visual-attestation tools own the detailed artifact checks. This
    control plane verifies their durable outputs and cross-checks the identities
    that would otherwise let an old green run be attached to a new requirement.
    """
    verdict = _load_json(evidence_root / "verdict.json", owner="normalized verdict")
    if verdict.get("status") != "ok" or str(verdict.get("exit")) != "0":
        raise UIReviewMatrixError(
            "verified requires normalized verdict status=ok and exit=0; "
            f"got status={verdict.get('status')!r} exit={verdict.get('exit')!r}"
        )
    if verdict.get("result") != "ok":
        raise UIReviewMatrixError("verified requires normalized verdict result=ok")
    try:
        executed = int(str(verdict.get("executed")))
    except (TypeError, ValueError) as error:
        raise UIReviewMatrixError("verified requires normalized verdict executed > 0") from error
    if executed <= 0:
        raise UIReviewMatrixError("verified requires normalized verdict executed > 0")
    if verdict.get("options", {}).get("sourceTreeDirty") is not False:
        raise UIReviewMatrixError("verified requires a clean sourceTreeDirty=false run")
    repository_for_provenance = repository_root or evidence_root.parents[3]
    source_tree_dirty = _git_source_tree_dirty(repository_for_provenance)
    if source_tree_dirty is None:
        raise UIReviewMatrixError("cannot determine current source tree cleanliness")
    if source_tree_dirty:
        raise UIReviewMatrixError("verified revalidation requires the current source tree to be clean")
    helper = _mapping(verdict.get("helper"), owner="verdict.helper")
    retention = helper.get("retention")
    if retention == "ephemeral":
        raise UIReviewMatrixError(
            "recording a matrix row requires explicit retained evidence; ephemeral visual output is inspection-only"
        )
    if retention not in {"retained", "promoted", "retained-explicit"}:
        raise UIReviewMatrixError(
            "verified evidence must declare retained/promoted retention before it can enter the matrix"
        )
    if _canonical_selector(helper.get("selector"), owner="verdict.helper.selector") != _canonical_selector(
        selector, owner="matrix selector"
    ):
        raise UIReviewMatrixError("selector does not match verdict.helper.selector")
    bundle_root = helper.get("bundleRoot")
    if not isinstance(bundle_root, str) or Path(bundle_root).resolve() != evidence_root.resolve():
        raise UIReviewMatrixError("evidence root does not match verdict.helper.bundleRoot")
    if evidence_root.name != run_id or Path(bundle_root).name != run_id:
        raise UIReviewMatrixError("runID must match the run bundle directory")
    options = _mapping(verdict.get("options"), owner="verdict.options")
    if options.get("datasetID") != dataset_id:
        raise UIReviewMatrixError("datasetID does not match normalized verdict")
    dataset_path = _dataset_path_for_id(
        root=repository_root or evidence_root.parents[3], dataset_id=dataset_id
    )
    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if options.get("datasetSHA256") != dataset_sha256:
        raise UIReviewMatrixError("evidence datasetSHA256 does not match the current UI World file")
    if verdict.get("runId") != run_id:
        raise UIReviewMatrixError("runID does not match normalized verdict")

    if not _git_source_commit_matches_current_or_matrix_receipt(
        repository_for_provenance,
        options.get("sourceCommit"),
    ):
        raise UIReviewMatrixError(
            "evidence sourceCommit is neither the current repository HEAD nor an "
            "ancestor with a matrix-only receipt diff"
        )

    artifacts = _mapping(verdict.get("artifacts"), owner="verdict.artifacts")
    artifact_paths: dict[str, Path] = {}
    for key in (
        "log",
        "xcresult",
        "uiVisualReviewManifest",
        "uiContactSheet",
        "uiQuick4Sheet",
        "uiReviewHtml",
        "uiVideo",
    ):
        artifact = artifacts.get(key)
        if not isinstance(artifact, str) or not Path(artifact).exists():
            raise UIReviewMatrixError(f"verified requires durable artifact: {key}")
        resolved_artifact = Path(artifact).resolve()
        try:
            resolved_artifact.relative_to(evidence_root.resolve())
        except ValueError as error:
            raise UIReviewMatrixError(
                f"verified artifact {key} must be inside the run evidence root"
            ) from error
        artifact_paths[key] = resolved_artifact

    manifest_path = artifact_paths["uiVisualReviewManifest"]
    manifest = _load_json(manifest_path, owner="visual review manifest")
    manifest_provenance = _mapping(manifest.get("provenance"), owner="visual review manifest provenance")
    manifest_selector = _canonical_selector(
        manifest_provenance.get("selector"), owner="visual review manifest selector"
    )
    if manifest_selector != _canonical_selector(selector, owner="matrix selector"):
        raise UIReviewMatrixError("selector does not match visual review manifest provenance")
    manifest_variant = manifest_provenance.get("variant")
    if not isinstance(manifest_variant, str) or not manifest_variant.strip():
        raise UIReviewMatrixError("visual review manifest provenance must contain variant")

    visual_review = _mapping(verdict.get("uiVisualReview"), owner="verdict.uiVisualReview")
    video_identity = _mapping(
        visual_review.get("videoIdentity"),
        owner="verdict.uiVisualReview.videoIdentity",
    )
    upstream_review = verdict.get("upstreamUiVisualReview")
    expected_video_run_id = str(video_identity.get("runID") or "")
    if isinstance(upstream_review, dict):
        upstream_review_root = upstream_review.get("reviewRoot")
        if isinstance(upstream_review_root, str) and upstream_review_root.strip():
            expected_video_run_id = Path(upstream_review_root).name
    if not expected_video_run_id:
        raise UIReviewMatrixError("verified requires video identity and review run identity")

    try:
        evidence_contract_result = validate_bundle(
            screenshot_dir=manifest_path.parent,
            manifest=manifest_path,
            contact_sheet=artifact_paths["uiContactSheet"],
            quick4_sheet=artifact_paths["uiQuick4Sheet"],
            video=artifact_paths["uiVideo"],
            review_html=artifact_paths["uiReviewHtml"],
            source_commit=options.get("sourceCommit"),
            dataset_id=dataset_id,
            dataset_sha256=options.get("datasetSHA256"),
            device=verdict.get("device"),
            video_identity=video_identity,
            expected_video_run_id=expected_video_run_id,
            selector=manifest_provenance["selector"],
            variant=manifest_variant,
        )
    except (OSError, TypeError, ValueError) as error:
        raise UIReviewMatrixError(f"visual evidence bundle validation failed: {error}") from error

    contract = _load_json(
        evidence_root / "artifacts" / "ui-evidence-contract.json",
        owner="machine evidence contract",
    )
    if contract.get("valid") is not True:
        raise UIReviewMatrixError("machine evidence contract is not valid")
    if not isinstance(contract.get("stepCount"), int) or contract["stepCount"] <= 0:
        raise UIReviewMatrixError("machine evidence contract must contain a positive stepCount")
    if not isinstance(contract.get("stepSha256"), list) or len(contract["stepSha256"]) != contract["stepCount"]:
        raise UIReviewMatrixError("machine evidence contract stepSha256 must cover every step")
    if contract["stepSha256"] != evidence_contract_result["stepSha256"]:
        raise UIReviewMatrixError("machine evidence contract step hashes do not match current PNGs")
    for artifact_key in ("contactSheet", "quick4Sheet"):
        if contract.get(artifact_key) != evidence_contract_result[artifact_key]:
            raise UIReviewMatrixError(
                f"machine evidence contract {artifact_key} does not match current artifact"
            )
    if contract.get("videoByteSize") != evidence_contract_result["videoByteSize"]:
        raise UIReviewMatrixError("machine evidence contract video size does not match current artifact")
    for artifact_key in ("videoSha256", "reviewHtmlSha256"):
        if contract.get(artifact_key) != evidence_contract_result[artifact_key]:
            raise UIReviewMatrixError(
                f"machine evidence contract {artifact_key} does not match current artifact"
            )
    contract_provenance = _mapping(contract.get("provenance"), owner="contract.provenance")
    contract_selector = _canonical_selector(
        contract_provenance.get("selector"), owner="contract.provenance.selector"
    )
    if contract_selector != _canonical_selector(selector, owner="matrix selector"):
        raise UIReviewMatrixError("selector does not match machine evidence contract")
    for key, expected in {
        "sourceCommit": options.get("sourceCommit"),
        "datasetID": dataset_id,
        "datasetSHA256": options.get("datasetSHA256"),
        "device": verdict.get("device"),
        "variant": manifest_variant,
    }.items():
        if contract_provenance.get(key) != expected:
            raise UIReviewMatrixError(f"machine evidence contract provenance mismatch for {key}")

    items = _non_empty_strings(
        [item.get("assetID") for item in manifest.get("items", []) if isinstance(item, dict)],
        owner="visual review manifest assetIDs",
    )
    if len(items) != len(set(items)):
        raise UIReviewMatrixError("visual review manifest assetIDs must be unique")
    state_labels = [
        str(item.get("stateLabel"))
        for item in manifest.get("items", [])
        if isinstance(item, dict) and item.get("stateLabel")
    ]
    if validate_steps:
        _validate_state_coverage(
            requirement=requirement,
            state_labels=state_labels,
            owner="visual manifest",
        )
    visual_checks = _non_empty_strings(
        _mapping(requirement.get("verification"), owner=f"{requirement.get('id')}.verification").get(
            "visualChecks"
        ),
        owner=f"{requirement.get('id')}.verification.visualChecks",
        minimum=2,
    )
    review_state = _load_json(
        evidence_root / "artifacts" / "ui-review" / "review_state.json",
        owner="visual review state",
    )
    if review_state.get("schema") != "kg.ui.review-state.v2":
        raise UIReviewMatrixError("visual review state must use schema kg.ui.review-state.v2")
    entries = review_state.get("entries")
    if not isinstance(entries, list):
        raise UIReviewMatrixError("visual review state entries must be a list")
    manifest_sha256 = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    expected_evidence_root_sha256 = _evidence_root_sha256(manifest_path.parent, manifest)
    latest_entry = entries[-1] if entries else None
    if not isinstance(latest_entry, dict) or latest_entry.get("status") != "pass":
        raise UIReviewMatrixError(
            "verified requires the latest visual attestation entry to be a complete pass"
        )
    try:
        asset_ids = _non_empty_strings(
            latest_entry.get("assetIDs"),
            owner="latest visual review entry.assetIDs",
            minimum=len(items),
        )
        entry_visual_checks = _non_empty_strings(
            latest_entry.get("visualChecks"),
            owner="latest visual review entry.visualChecks",
        )
        _non_empty_string(latest_entry.get("reviewer"), owner="latest visual review entry.reviewer")
        _non_empty_string(latest_entry.get("observedAt"), owner="latest visual review entry.observedAt")
        _non_empty_string(latest_entry.get("notes"), owner="latest visual review entry.notes")
    except UIReviewMatrixError as error:
        raise UIReviewMatrixError(f"latest visual attestation is invalid: {error}") from error
    all_steps_passed = (
        len(asset_ids) == len(items)
        and set(asset_ids) == set(items)
        and set(visual_checks).issubset(set(entry_visual_checks))
        and latest_entry.get("manifestSHA256") == manifest_sha256
        and latest_entry.get("evidenceRootSHA256") == expected_evidence_root_sha256
        and latest_entry.get("provenance") == manifest_provenance
    )
    if not all_steps_passed:
        raise UIReviewMatrixError("verified requires an all-steps visual attestation with status=pass")

    provenance = {
        "sourceCommit": _non_empty_string(options.get("sourceCommit"), owner="verdict.options.sourceCommit"),
        "datasetSHA256": _non_empty_string(
            options.get("datasetSHA256"), owner="verdict.options.datasetSHA256"
        ),
        "device": _non_empty_string(verdict.get("device"), owner="verdict.device"),
        "manifestSHA256": manifest_sha256,
    }
    return provenance


def _state_label_matches(label: str, step: str, aliases: list[str]) -> bool:
    """Match a logical state to an exact capture label or run-many prefix.

    The evidence manifest prefixes capture names with the XCTest selector.  A
    requirement may explicitly declare aliases when the product state is
    canonical but an older test uses a different capture name.  Arbitrary
    substring matching is deliberately forbidden.
    """
    for candidate in [step, *aliases]:
        if label == candidate or label.endswith(f"-{candidate}"):
            return True
    return False


def _state_aliases(requirement: dict[str, Any]) -> dict[str, list[str]]:
    raw = _mapping(
        _mapping(requirement.get("verification"), owner=f"{requirement.get('id')}.verification").get(
            "stateAliases", {}
        ),
        owner=f"{requirement.get('id')}.verification.stateAliases",
    )
    aliases: dict[str, list[str]] = {}
    for step, values in raw.items():
        aliases[step] = _unique_non_empty_strings(
            values,
            owner=f"{requirement.get('id')}.verification.stateAliases.{step}",
        )
    return aliases


def _validate_state_coverage(
    *,
    requirement: dict[str, Any],
    state_labels: list[str],
    owner: str,
) -> None:
    verification = _mapping(requirement.get("verification"), owner=f"{requirement.get('id')}.verification")
    required_steps = _unique_non_empty_strings(
        verification.get("requiredSteps"),
        owner=f"{requirement.get('id')}.verification.requiredSteps",
        minimum=2,
    )
    counterexample_steps = _unique_non_empty_strings(
        verification.get("counterexampleSteps"),
        owner=f"{requirement.get('id')}.verification.counterexampleSteps",
    )
    aliases = _state_aliases(requirement)

    def matches(step: str) -> list[int]:
        return [
            index
            for index, label in enumerate(state_labels)
            if _state_label_matches(label, step, aliases.get(step, []))
        ]

    required_matches = {step: matches(step) for step in required_steps}
    missing = [step for step, indexes in required_matches.items() if not indexes]
    duplicate = [step for step, indexes in required_matches.items() if len(indexes) != 1]
    if missing:
        raise UIReviewMatrixError(f"{owner} does not cover required steps: {missing}")
    if duplicate:
        raise UIReviewMatrixError(f"{owner} required visual steps must map one-to-one to assets: {duplicate}")
    required_assets = [indexes[0] for indexes in required_matches.values()]
    if len(set(required_assets)) != len(required_assets):
        raise UIReviewMatrixError(f"{owner} required visual steps must map to distinct assets")

    counterexample_matches = {step: matches(step) for step in counterexample_steps}
    counterexample_missing_or_duplicate = [
        step for step, indexes in counterexample_matches.items() if len(indexes) != 1
    ]
    if counterexample_missing_or_duplicate:
        raise UIReviewMatrixError(
            f"{owner} does not contain one distinct asset for counterexamples: "
            f"{counterexample_missing_or_duplicate}"
        )
    counterexample_assets = {indexes[0] for indexes in counterexample_matches.values()}
    if set(required_assets) & counterexample_assets:
        raise UIReviewMatrixError(
            f"{owner} required visual steps and counterexamples must use disjoint assets"
        )


def _manifest_state_labels(evidence_root: Path) -> list[str]:
    manifest = _load_json(
        evidence_root / "artifacts" / "ui-review" / "review_manifest.json",
        owner="visual review manifest",
    )
    labels = [
        str(item.get("stateLabel"))
        for item in manifest.get("items", [])
        if isinstance(item, dict) and item.get("stateLabel")
    ]
    if not labels:
        raise UIReviewMatrixError("visual review manifest has no state labels")
    return labels


def _validate_aggregate_state_coverage(
    *,
    requirement: dict[str, Any],
    bundles: list[dict[str, Any]],
) -> None:
    """Validate required/counterexample states across a selector union.

    Each bundle is still fully validated independently.  This second gate
    only unions state labels for one requirement, so P4/P5/P15 can use their
    intentionally separate success and counterexample selectors without
    weakening one-to-one asset or counterexample coverage.
    """
    verification = _mapping(requirement.get("verification"), owner=f"{requirement.get('id')}.verification")
    required_steps = _unique_non_empty_strings(
        verification.get("requiredSteps"),
        owner=f"{requirement.get('id')}.verification.requiredSteps",
        minimum=2,
    )
    counterexample_steps = _unique_non_empty_strings(
        verification.get("counterexampleSteps"),
        owner=f"{requirement.get('id')}.verification.counterexampleSteps",
    )
    aliases = _state_aliases(requirement)
    occurrences: list[tuple[str, int, str]] = []
    for bundle in bundles:
        for item_index, label in enumerate(bundle["stateLabels"]):
            occurrences.append((bundle["runID"], item_index, label))

    def matches(step: str) -> list[tuple[str, int, str]]:
        return [
            occurrence
            for occurrence in occurrences
            if _state_label_matches(occurrence[2], step, aliases.get(step, []))
        ]

    missing_required = [step for step in required_steps if not matches(step)]
    duplicate_required = [step for step in required_steps if len(matches(step)) != 1]
    missing_counterexamples = [
        step for step in counterexample_steps if len(matches(step)) != 1
    ]
    if missing_required or duplicate_required or missing_counterexamples:
        details = {
            "missingRequired": missing_required,
            "duplicateRequired": duplicate_required,
            "counterexampleCoverage": missing_counterexamples,
        }
        raise UIReviewMatrixError(
            f"aggregate visual coverage incomplete for {requirement.get('id')}: {details}"
        )
    required_occurrences = {matches(step)[0][:2] for step in required_steps}
    counterexample_occurrences = {matches(step)[0][:2] for step in counterexample_steps}
    if required_occurrences & counterexample_occurrences:
        raise UIReviewMatrixError(
            f"aggregate visual coverage reuses an asset for required/counterexample state "
            f"in {requirement.get('id')}"
        )


def record_requirement(
    data: dict[str, Any],
    *,
    requirement_id: str,
    status: str,
    root: Path,
    selector: str | None = None,
    dataset_id: str | None = None,
    run_id: str | None = None,
    evidence_root: str | None = None,
    blockers: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if requirement_id not in REQUIRED_IDS:
        raise UIReviewMatrixError(f"requirement id must be one of {REQUIRED_IDS}")
    if status not in STATUSES:
        raise UIReviewMatrixError(f"invalid verification status: {status}")
    requirements = data.get("requirements")
    if not isinstance(requirements, list):
        raise UIReviewMatrixError("requirements must be a list")
    requirement = next(
        (value for value in requirements if isinstance(value, dict) and value.get("id") == requirement_id),
        None,
    )
    if requirement is None:
        raise UIReviewMatrixError(f"missing requirement {requirement_id}")

    verification = _mapping(requirement.get("verification"), owner=f"{requirement_id}.verification")
    if status == "verified":
        for value, owner in (
            (selector, "--selector"),
            (dataset_id, "--dataset-id"),
            (run_id, "--run-id"),
            (evidence_root, "--evidence-root"),
        ):
            _non_empty_string(value, owner=owner)
        normalized_selector = _canonical_selector(selector, owner="--selector")
        _require_fixture_ids(requirement, root=root, dataset_id=dataset_id)
        retained_root, stored_root = _resolve_rooted_path(
            evidence_root, root=root, owner="--evidence-root"
        )
        provenance = _evidence_provenance(
            retained_root,
            requirement=requirement,
            selector=normalized_selector,
            dataset_id=dataset_id,
            run_id=run_id,
            repository_root=root,
        )
        verification.update(
            {
                "status": "verified",
                "selector": normalized_selector,
                "datasetID": dataset_id,
                "runID": run_id,
                "evidenceRoot": stored_root,
                **provenance,
                "blockers": [],
            }
        )
    else:
        blocker_values = blockers or []
        _non_empty_strings(blocker_values, owner="--blocker")
        verification["status"] = status
        verification["blockers"] = blocker_values
        if status != "verified":
            for field in (
                "selector",
                "datasetID",
                "runID",
                "evidenceRoot",
                "sourceCommit",
                "datasetSHA256",
                "device",
                "manifestSHA256",
            ):
                verification.pop(field, None)

    history = verification.setdefault("history", [])
    if not isinstance(history, list):
        raise UIReviewMatrixError(f"{requirement_id}.verification.history must be a list")
    history.append(
        {
            "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": verification["status"],
            "selector": verification.get("selector"),
            "datasetID": verification.get("datasetID"),
            "runID": verification.get("runID"),
            "evidenceRoot": verification.get("evidenceRoot"),
            "blockers": list(verification.get("blockers") or []),
        }
    )
    return data, verification


def _atomic_write_matrix(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
        directory_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def record_many(
    data: dict[str, Any],
    *,
    summary: dict[str, Any],
    root: Path,
) -> list[dict[str, Any]]:
    """Record a completed run-many batch only after every run is attested.

    The batch command is intentionally all-or-nothing: it does not turn a
    machine pass into a visual pass, and it does not write a partial matrix if
    one requirement fails provenance validation.
    """
    if summary.get("schema") != "kg.ios.ui-run-many.v1":
        raise UIReviewMatrixError("run-many summary schema is invalid")
    if summary.get("status") != "passed_unattested":
        raise UIReviewMatrixError("record-many requires a machine-passed run-many summary")
    executions = summary.get("executions")
    if not isinstance(executions, list) or not executions:
        raise UIReviewMatrixError("run-many summary has no executions")
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, execution in enumerate(executions):
        execution = _mapping(execution, owner=f"executions[{index}]")
        if execution.get("status") != "passed_unattested":
            raise UIReviewMatrixError(f"executions[{index}] is not machine-passed")
        requirement_ids = execution.get("requirementIDs")
        if not isinstance(requirement_ids, list) or not requirement_ids:
            requirement_id = execution.get("requirementID")
            requirement_ids = [requirement_id] if requirement_id else []
        for requirement_id in requirement_ids:
            if not isinstance(requirement_id, str):
                raise UIReviewMatrixError(f"executions[{index}] has invalid requirementID")
            requirement = next(
                (
                    value
                    for value in data.get("requirements", [])
                    if isinstance(value, dict) and value.get("id") == requirement_id
                ),
                None,
            )
            if requirement is None:
                raise UIReviewMatrixError(f"missing requirement {requirement_id}")
            selector = _canonical_selector(
                execution.get("selector"), owner=f"executions[{index}].selector"
            )
            dataset_id = _non_empty_string(
                execution.get("datasetID"), owner=f"executions[{index}].datasetID"
            )
            bundle_root_value = _non_empty_string(
                execution.get("bundleRoot"), owner=f"executions[{index}].bundleRoot"
            )
            run_id = Path(bundle_root_value).name
            retained_root, stored_root = _resolve_rooted_path(
                bundle_root_value,
                root=root,
                owner=f"executions[{index}].bundleRoot",
            )
            _require_fixture_ids(requirement, root=root, dataset_id=dataset_id)
            provenance = _evidence_provenance(
                retained_root,
                requirement=requirement,
                selector=selector,
                dataset_id=dataset_id,
                run_id=run_id,
                repository_root=root,
                validate_steps=False,
            )
            grouped.setdefault(requirement_id, []).append(
                {
                    "selector": selector,
                    "datasetID": dataset_id,
                    "runID": run_id,
                    "evidenceRoot": stored_root,
                    "stateLabels": _manifest_state_labels(retained_root),
                    **provenance,
                }
            )

    recorded: list[dict[str, Any]] = []
    requirements = {
        value.get("id"): value
        for value in data.get("requirements", [])
        if isinstance(value, dict) and value.get("id")
    }
    for requirement_id, bundles in grouped.items():
        requirement = requirements[requirement_id]
        if len({(bundle["selector"], bundle["runID"]) for bundle in bundles}) != len(bundles):
            raise UIReviewMatrixError(
                f"record-many cannot use duplicate selector/runID bundles for {requirement_id}"
            )
        _validate_aggregate_state_coverage(requirement=requirement, bundles=bundles)
        verification = _mapping(
            requirement.get("verification"), owner=f"{requirement_id}.verification"
        )
        primary = bundles[0]
        verification.update(
            {
                "status": "verified",
                "selector": primary["selector"],
                "datasetID": primary["datasetID"],
                "runID": primary["runID"],
                "evidenceRoot": primary["evidenceRoot"],
                "sourceCommit": primary["sourceCommit"],
                "datasetSHA256": primary["datasetSHA256"],
                "device": primary["device"],
                "manifestSHA256": primary["manifestSHA256"],
                "evidenceBundles": [
                    {
                        key: bundle[key]
                        for key in (
                            "selector",
                            "datasetID",
                            "runID",
                            "evidenceRoot",
                            "sourceCommit",
                            "datasetSHA256",
                            "device",
                            "manifestSHA256",
                        )
                    }
                    for bundle in bundles
                ],
                "blockers": [],
            }
        )
        history = verification.setdefault("history", [])
        if not isinstance(history, list):
            raise UIReviewMatrixError(f"{requirement_id}.verification.history must be a list")
        history.append(
            {
                "recordedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "status": "verified",
                "selector": primary["selector"],
                "datasetID": primary["datasetID"],
                "runID": primary["runID"],
                "evidenceRoot": primary["evidenceRoot"],
                "evidenceBundleCount": len(bundles),
                "blockers": [],
            }
        )
        recorded.append({"requirementID": requirement_id, "verification": verification})
    return recorded


def load_matrix(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise UIReviewMatrixError(f"cannot read matrix {path}: {error}") from error
    return _mapping(data, owner="matrix")


def validate_matrix(
    data: dict[str, Any],
    *,
    root: Path,
    require_complete: bool = False,
    require_fixtures: bool = False,
    dataset_id: str | None = None,
    requirement_id: str | None = None,
) -> dict[str, Any]:
    if data.get("schema") != SCHEMA:
        raise UIReviewMatrixError(f"matrix schema must be {SCHEMA}")

    report = _mapping(data.get("report"), owner="report")
    report_dir = report.get("directory")
    if not isinstance(report_dir, str) or not report_dir.strip():
        raise UIReviewMatrixError("report.directory must be a non-empty string")
    resolved_report_dir, _ = _resolve_rooted_path(
        report_dir, root=root, owner="report.directory"
    )
    report_root = root.resolve()
    images = _non_empty_strings(report.get("images"), owner="report.images", minimum=15)
    if set(images) != {f"p{index}.PNG" for index in range(1, 16)}:
        raise UIReviewMatrixError("report.images must contain exactly p1.PNG through p15.PNG")
    missing_report_images = []
    for image in images:
        resolved_image = (resolved_report_dir / image).resolve()
        try:
            resolved_image.relative_to(report_root)
        except ValueError as error:
            raise UIReviewMatrixError(
                f"report image resolves outside repository root: {image}"
            ) from error
        if not resolved_image.is_file():
            missing_report_images.append(image)
    if missing_report_images:
        raise UIReviewMatrixError(f"report images do not exist: {missing_report_images}")

    requirements = data.get("requirements")
    if not isinstance(requirements, list):
        raise UIReviewMatrixError("requirements must be a list")
    by_id: dict[str, dict[str, Any]] = {}
    for index, raw_requirement in enumerate(requirements):
        owner = f"requirements[{index}]"
        requirement = _mapping(raw_requirement, owner=owner)
        current_requirement_id = requirement.get("id")
        if current_requirement_id not in REQUIRED_IDS:
            raise UIReviewMatrixError(f"{owner}.id must be one of {REQUIRED_IDS}")
        if current_requirement_id in by_id:
            raise UIReviewMatrixError(f"duplicate requirement id {current_requirement_id}")
        by_id[current_requirement_id] = requirement

        for field in ("title", "surface"):
            if not isinstance(requirement.get(field), str) or not requirement[field].strip():
                raise UIReviewMatrixError(f"{owner}.{field} must be a non-empty string")
            if requirement.get("reportImage") != f"{current_requirement_id.lower()}.PNG":
                raise UIReviewMatrixError(f"{owner}.reportImage must match {current_requirement_id.lower()}.PNG")
        source_refs = _non_empty_strings(requirement.get("sourceRefs"), owner=f"{owner}.sourceRefs")
        for source_ref in source_refs:
            _resolve_rooted_path(source_ref, root=root, owner=f"{owner}.sourceRefs")
        _non_empty_strings(requirement.get("requiredFixtureIDs"), owner=f"{owner}.requiredFixtureIDs")
        _non_empty_strings(requirement.get("acceptance"), owner=f"{owner}.acceptance", minimum=2)
        _non_empty_strings(requirement.get("counterexamples"), owner=f"{owner}.counterexamples")

        verification = _mapping(requirement.get("verification"), owner=f"{owner}.verification")
        status = verification.get("status")
        if status not in STATUSES:
            raise UIReviewMatrixError(f"{owner}.verification.status is invalid: {status!r}")
        required_steps = _unique_non_empty_strings(
            verification.get("requiredSteps"),
            owner=f"{owner}.verification.requiredSteps",
            minimum=2,
        )
        _non_empty_strings(
            verification.get("visualChecks"),
            owner=f"{owner}.verification.visualChecks",
            minimum=2,
        )
        counterexample_steps = _unique_non_empty_strings(
            verification.get("counterexampleSteps"),
            owner=f"{owner}.verification.counterexampleSteps",
        )
        if set(required_steps) & set(counterexample_steps):
            raise UIReviewMatrixError(
                f"{owner}.verification requiredSteps and counterexampleSteps must be disjoint"
            )
        if status in {"pending", "in_progress", "blocked"}:
            _non_empty_strings(
                verification.get("blockers"),
                owner=f"{owner}.verification.blockers",
            )
        if status == "verified":
            for field in (
                "selector",
                "datasetID",
                "runID",
                "evidenceRoot",
                "sourceCommit",
                "datasetSHA256",
                "device",
                "manifestSHA256",
            ):
                value = verification.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise UIReviewMatrixError(
                        f"{owner}.verification.{field} is required for verified status"
                    )
            if verification.get("blockers") not in (None, []):
                raise UIReviewMatrixError(f"{owner}.verification.blockers must be empty when verified")
            _require_fixture_ids(
                requirement,
                root=root,
                dataset_id=verification["datasetID"],
            )
            raw_bundles = verification.get("evidenceBundles")
            if raw_bundles is None:
                raw_bundles = [
                    {
                        "selector": verification["selector"],
                        "datasetID": verification["datasetID"],
                        "runID": verification["runID"],
                        "evidenceRoot": verification["evidenceRoot"],
                        "sourceCommit": verification["sourceCommit"],
                        "datasetSHA256": verification["datasetSHA256"],
                        "device": verification["device"],
                        "manifestSHA256": verification["manifestSHA256"],
                    }
                ]
            if not isinstance(raw_bundles, list) or not raw_bundles:
                raise UIReviewMatrixError(
                    f"{owner}.verification.evidenceBundles must be a non-empty list"
                )
            fresh_bundles: list[dict[str, Any]] = []
            for bundle_index, raw_bundle in enumerate(raw_bundles):
                bundle = _mapping(
                    raw_bundle,
                    owner=f"{owner}.verification.evidenceBundles[{bundle_index}]",
                )
                bundle_selector = _canonical_selector(
                    bundle.get("selector"),
                    owner=f"{owner}.verification.evidenceBundles[{bundle_index}].selector",
                )
                bundle_dataset_id = _non_empty_string(
                    bundle.get("datasetID"),
                    owner=f"{owner}.verification.evidenceBundles[{bundle_index}].datasetID",
                )
                bundle_run_id = _non_empty_string(
                    bundle.get("runID"),
                    owner=f"{owner}.verification.evidenceBundles[{bundle_index}].runID",
                )
                bundle_evidence_root = _non_empty_string(
                    bundle.get("evidenceRoot"),
                    owner=f"{owner}.verification.evidenceBundles[{bundle_index}].evidenceRoot",
                )
                bundle_root, stored_bundle_root = _resolve_rooted_path(
                    bundle_evidence_root,
                    root=root,
                    owner=f"{owner}.verification.evidenceBundles[{bundle_index}].evidenceRoot",
                )
                if bundle_dataset_id != verification["datasetID"]:
                    raise UIReviewMatrixError(
                        f"{owner}.verification evidence bundle datasetID differs from primary"
                    )
                fresh_provenance = _evidence_provenance(
                    bundle_root,
                    requirement=requirement,
                    selector=bundle_selector,
                    dataset_id=bundle_dataset_id,
                    run_id=bundle_run_id,
                    repository_root=root,
                    validate_steps=False,
                )
                for provenance_key, fresh_value in fresh_provenance.items():
                    if bundle.get(provenance_key) != fresh_value:
                        raise UIReviewMatrixError(
                            f"{owner}.verification.evidenceBundles[{bundle_index}]."
                            f"{provenance_key} does not match current evidence"
                        )
                fresh_bundles.append(
                    {
                        "selector": bundle_selector,
                        "datasetID": bundle_dataset_id,
                        "runID": bundle_run_id,
                        "evidenceRoot": stored_bundle_root,
                        "stateLabels": _manifest_state_labels(bundle_root),
                        **fresh_provenance,
                    }
                )
            primary = fresh_bundles[0]
            for key in (
                "selector",
                "datasetID",
                "runID",
                "evidenceRoot",
                "sourceCommit",
                "datasetSHA256",
                "device",
                "manifestSHA256",
            ):
                expected = primary[key]
                if verification.get(key) != expected:
                    raise UIReviewMatrixError(
                        f"{owner}.verification.{key} does not match primary evidence bundle"
                    )
            _validate_aggregate_state_coverage(requirement=requirement, bundles=fresh_bundles)
        history = verification.get("history")
        if history is not None and not isinstance(history, list):
            raise UIReviewMatrixError(f"{owner}.verification.history must be a list")

    missing = [requirement_id for requirement_id in REQUIRED_IDS if requirement_id not in by_id]
    extra = sorted(set(by_id) - set(REQUIRED_IDS))
    if missing or extra or len(requirements) != len(REQUIRED_IDS):
        raise UIReviewMatrixError(f"requirements must be exactly P1-P15 missing={missing} extra={extra}")

    pending = [
        requirement_id
        for requirement_id in REQUIRED_IDS
        if by_id[requirement_id]["verification"]["status"] != "verified"
    ]
    if require_complete and pending:
        raise UIReviewMatrixError(f"strict completion blocked; unresolved requirements={pending}")
    if require_fixtures and not dataset_id:
        raise UIReviewMatrixError("--require-fixtures requires --dataset-id")
    if require_fixtures and requirement_id is None:
        raise UIReviewMatrixError("--require-fixtures requires --requirement-id")

    if requirement_id is not None and requirement_id not in by_id:
        raise UIReviewMatrixError(f"requirement id must be one of {REQUIRED_IDS}")

    fixture_gaps: dict[str, list[str]] = {}
    if dataset_id:
        available = _fixture_ids_for_dataset(root=root, dataset_id=dataset_id)
        fixture_requirements = (
            {requirement_id: by_id[requirement_id]}
            if requirement_id is not None
            else by_id
        )
        for current_requirement_id, requirement in fixture_requirements.items():
            missing_fixture_ids = sorted(
                set(requirement["requiredFixtureIDs"]) - available
            )
            if missing_fixture_ids:
                fixture_gaps[current_requirement_id] = missing_fixture_ids
        if require_fixtures and fixture_gaps:
            raise UIReviewMatrixError(
                f"required fixture IDs are not declared by UI World {dataset_id}: {fixture_gaps}"
            )

    missing_source_refs = []
    for requirement_id, requirement in by_id.items():
        for source_ref in requirement["sourceRefs"]:
            resolved_source_ref, _ = _resolve_rooted_path(
                source_ref, root=root, owner=f"{requirement_id}.sourceRefs"
            )
            if not resolved_source_ref.is_file():
                missing_source_refs.append(f"{requirement_id}:{source_ref}")
    if missing_source_refs:
        raise UIReviewMatrixError(f"sourceRefs do not exist: {missing_source_refs}")

    return {
        "schema": SCHEMA,
        "requirementCount": len(REQUIRED_IDS),
        "verified": len(REQUIRED_IDS) - len(pending),
        "pending": pending,
        "complete": not pending,
        "fixtureGaps": fixture_gaps,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["validate", "record", "record-many"])
    parser.add_argument("matrix", type=Path)
    parser.add_argument("requirement_id", nargs="?")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--strict-complete", action="store_true")
    parser.add_argument("--require-fixtures", action="store_true")
    parser.add_argument("--requirement-id", dest="fixture_requirement_id")
    parser.add_argument("--dataset-id")
    parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--selector")
    parser.add_argument("--run-id")
    parser.add_argument("--evidence-root")
    parser.add_argument("--blocker", action="append", default=[])
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "validate":
            data = load_matrix(args.matrix)
            result = validate_matrix(
                data,
                root=args.root,
                require_complete=args.strict_complete,
                require_fixtures=args.require_fixtures,
                dataset_id=args.dataset_id,
                requirement_id=args.fixture_requirement_id,
            )
        elif args.command == "record":
            if not args.requirement_id or not args.status:
                raise UIReviewMatrixError("record requires requirement_id and --status")
            lock_key = hashlib.sha256(str(args.matrix.resolve()).encode()).hexdigest()
            lock_path = Path(tempfile.gettempdir()) / f"kg-ios-ui-review-matrix-{lock_key}.lock"
            with lock_path.open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                data = load_matrix(args.matrix)
                data, verification = record_requirement(
                    data,
                    requirement_id=args.requirement_id,
                    status=args.status,
                    root=args.root,
                    selector=args.selector,
                    dataset_id=args.dataset_id,
                    run_id=args.run_id,
                    evidence_root=args.evidence_root,
                    blockers=args.blocker,
                )
                validate_matrix(data, root=args.root)
                _atomic_write_matrix(args.matrix, data)
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            result = {"requirementID": args.requirement_id, "verification": verification}
        else:
            if not args.summary:
                raise UIReviewMatrixError("record-many requires --summary")
            lock_key = hashlib.sha256(str(args.matrix.resolve()).encode()).hexdigest()
            lock_path = Path(tempfile.gettempdir()) / f"kg-ios-ui-review-matrix-{lock_key}.lock"
            with lock_path.open("a+") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                data = load_matrix(args.matrix)
                summary = _load_json(args.summary, owner="run-many summary")
                records = record_many(data, summary=summary, root=args.root)
                validate_matrix(data, root=args.root)
                _atomic_write_matrix(args.matrix, data)
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            result = {"records": records}
    except (OSError, UIReviewMatrixError) as error:
        print(json.dumps({"schema": SCHEMA, "valid": False, "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({"valid": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
