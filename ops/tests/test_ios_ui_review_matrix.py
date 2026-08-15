from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "ops" / "fixtures" / "ios_ui_review_matrix.json"
sys.path.insert(0, str(ROOT / "ops"))
import ios_ui_review_matrix as MODULE  # noqa: E402
from uitest_evidence_contract import png_metadata  # noqa: E402
from uitest_review_attest import evidence_root_sha256  # noqa: E402


ONE_BY_ONE_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _pending_matrix() -> dict:
    data = MODULE.load_matrix(MATRIX)
    for requirement in data["requirements"]:
        verification = requirement["verification"]
        verification["status"] = "pending"
        verification["blockers"] = ["synthetic pending state for structural test"]
    return data


def test_matrix_has_exactly_fifteen_report_requirements() -> None:
    result = MODULE.validate_matrix(MODULE.load_matrix(MATRIX), root=ROOT)

    assert result["requirementCount"] == 15
    assert result["verified"] == 15
    assert result["complete"] is True
    assert result["pending"] == []


def test_matrix_cli_accepts_validate_entrypoint() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "ios_ui_review_matrix.py"),
            "validate",
            str(MATRIX),
            "--root",
            str(ROOT),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert '"valid": true' in result.stdout


def test_strict_completion_is_fail_closed_until_every_run_is_attested() -> None:
    data = _pending_matrix()
    with pytest.raises(MODULE.UIReviewMatrixError, match="strict completion blocked"):
        MODULE.validate_matrix(data, root=ROOT, require_complete=True)


def test_fixture_gate_reports_undeclared_requirement_fixtures() -> None:
    with pytest.raises(MODULE.UIReviewMatrixError, match="--requirement-id"):
        MODULE.validate_matrix(
            _pending_matrix(),
            root=ROOT,
            dataset_id="marketing_demo",
            require_fixtures=True,
        )


def test_fixture_gate_can_scope_one_requirement() -> None:
    result = MODULE.validate_matrix(
        _pending_matrix(),
        root=ROOT,
        dataset_id="marketing_demo",
        requirement_id="P11",
        require_fixtures=True,
    )

    assert result["fixtureGaps"] == {}


@pytest.mark.parametrize("requirement_id", ["P1", "P2", "P8", "P9"])
def test_fixture_gate_accepts_canonical_scenario_contract_ids(requirement_id: str) -> None:
    result = MODULE.validate_matrix(
        _pending_matrix(),
        root=ROOT,
        dataset_id="marketing_demo",
        requirement_id=requirement_id,
        require_fixtures=True,
    )

    assert result["fixtureGaps"] == {}


def test_fixture_gate_rejects_unknown_requirement_scope() -> None:
    with pytest.raises(MODULE.UIReviewMatrixError, match="requirement id"):
        MODULE.validate_matrix(
            _pending_matrix(),
            root=ROOT,
            dataset_id="marketing_demo",
            requirement_id="P99",
            require_fixtures=True,
        )


def test_matrix_rejects_missing_report_requirement() -> None:
    data = _pending_matrix()
    data["requirements"] = data["requirements"][:-1]

    with pytest.raises(MODULE.UIReviewMatrixError, match="exactly P1-P15"):
        MODULE.validate_matrix(data, root=ROOT)


def test_matrix_rejects_duplicate_required_or_counterexample_labels() -> None:
    data = _pending_matrix()
    p3 = next(item for item in data["requirements"] if item["id"] == "P3")
    p3["verification"]["requiredSteps"].append("reader")
    with pytest.raises(MODULE.UIReviewMatrixError, match="must not contain duplicate labels"):
        MODULE.validate_matrix(data, root=ROOT)


def test_aggregate_coverage_unions_distinct_selector_bundles() -> None:
    requirement = {
        "id": "P4",
        "verification": {
            "requiredSteps": ["open", "change"],
            "counterexampleSteps": ["dark"],
            "stateAliases": {"change": ["changed"]},
        },
    }

    MODULE._validate_aggregate_state_coverage(
        requirement=requirement,
        bundles=[
            {"runID": "run-a", "stateLabels": ["selector-open"]},
            {"runID": "run-b", "stateLabels": ["selector-changed", "selector-dark"]},
        ],
    )


def test_aggregate_coverage_reports_all_missing_states_without_partial_write() -> None:
    requirement = {
        "id": "P4",
        "verification": {
            "requiredSteps": ["open", "change"],
            "counterexampleSteps": ["dark", "dynamic"],
        },
    }

    with pytest.raises(MODULE.UIReviewMatrixError, match="dynamic") as error:
        MODULE._validate_aggregate_state_coverage(
            requirement=requirement,
            bundles=[
                {"runID": "run-a", "stateLabels": ["selector-open", "selector-dark"]},
            ],
        )
    assert "change" in str(error.value)

    data = _pending_matrix()
    p3 = next(item for item in data["requirements"] if item["id"] == "P3")
    p3["verification"]["counterexampleSteps"].append("missing-chapter")
    with pytest.raises(MODULE.UIReviewMatrixError, match="must not contain duplicate labels"):
        MODULE.validate_matrix(data, root=ROOT)


def test_verified_row_requires_run_provenance() -> None:
    data = _pending_matrix()
    verification = data["requirements"][0]["verification"]
    verification["status"] = "verified"
    verification["selector"] = "Example/test"
    verification["datasetID"] = "marketing_demo"
    verification["runID"] = ""

    with pytest.raises(MODULE.UIReviewMatrixError, match="runID"):
        MODULE.validate_matrix(data, root=ROOT)


@pytest.mark.parametrize(
    "selector",
    ["ExampleTests.swift", "--file ExampleTests.swift", "--grep Example", "Example/test"],
)
def test_verified_selector_must_be_an_exact_test_method(selector: str) -> None:
    with pytest.raises(MODULE.UIReviewMatrixError, match="exact ClassName/testMethodName"):
        MODULE._canonical_selector(selector, owner="selector")


def test_verified_row_with_fake_provenance_is_rejected() -> None:
    data = MODULE.load_matrix(MATRIX)
    verification = data["requirements"][0]["verification"]
    verification.update(
        {
            "status": "verified",
            "selector": "Example/test",
            "datasetID": "dataset",
            "runID": "20260813-000000-1",
            "evidenceRoot": "sha256:example",
            "sourceCommit": "commit",
            "datasetSHA256": "dataset-sha",
            "device": "device",
            "manifestSHA256": "manifest-sha",
            "blockers": [],
        }
    )

    with pytest.raises(MODULE.UIReviewMatrixError, match="UI World dataset dataset"):
        MODULE.validate_matrix(data, root=ROOT)


def test_record_blocker_appends_history_without_claiming_verified() -> None:
    data = MODULE.load_matrix(MATRIX)

    _, verification = MODULE.record_requirement(
        data,
        requirement_id="P6",
        status="blocked",
        root=ROOT,
        blockers=["fixture state is not injected yet"],
    )

    assert verification["status"] == "blocked"
    assert verification["blockers"] == ["fixture state is not injected yet"]
    assert verification["history"][-1]["status"] == "blocked"


def test_record_verified_requires_machine_and_visual_provenance(tmp_path: Path) -> None:
    data = MODULE.load_matrix(MATRIX)
    dataset_path = tmp_path / "ops" / "fixtures" / "ui_worlds" / "dataset-1.json"
    dataset_path.parent.mkdir(parents=True)
    dataset = json.loads((ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json").read_text())
    dataset["datasetID"] = "dataset-1"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    dataset_sha256 = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    evidence = tmp_path / "build" / "snapshots" / "uitest-evidence" / "run-1"
    review_root = evidence / "artifacts" / "ui-review"
    review_root.mkdir(parents=True)
    (evidence / "artifacts" / "delegate.stderr.log").write_text("log", encoding="utf-8")
    (evidence / "artifacts" / "Test.xcresult").mkdir()
    (review_root / "UIreview.html").write_text("KG UITest Run Review", encoding="utf-8")
    for name in (
        "01-reader.png",
        "02-toc-open.png",
        "03-chapter-select.png",
        "04-navigation-result.png",
        "05-navigation-failure.png",
        "06-missing-chapter.png",
        "contact_sheet.png",
        "quick4_contact_sheet.png",
    ):
        (review_root / name).write_bytes(ONE_BY_ONE_PNG)
    (review_root / "uitest-videos").mkdir()
    (review_root / "uitest-videos" / "run.mp4").write_bytes(b"video")
    (evidence / "verdict.json").write_text(
        json.dumps(
            {
                "status": "ok",
                "result": "ok",
                "exit": "0",
                "executed": "1",
                "runId": "run-1",
                "device": "UDID-1",
                    "options": {
                        "sourceCommit": "commit-1",
                        "datasetID": "dataset-1",
                        "datasetSHA256": dataset_sha256,
                        "sourceTreeDirty": False,
                    },
                    "upstreamUiVisualReview": {
                        "reviewRoot": str(evidence),
                    },
                    "uiVisualReview": {
                        "videoIdentity": {
                            "runID": "run-1",
                            "file": "run.mp4",
                            "sha256": hashlib.sha256(b"video").hexdigest(),
                        },
                    },
                    "helper": {
                    "selector": "Example/testExample",
                    "bundleRoot": str(evidence),
                },
                "artifacts": {
                    "log": str(evidence / "artifacts" / "delegate.stderr.log"),
                    "xcresult": str(evidence / "artifacts" / "Test.xcresult"),
                    "uiVisualReviewManifest": str(review_root / "review_manifest.json"),
                    "uiContactSheet": str(review_root / "contact_sheet.png"),
                    "uiQuick4Sheet": str(review_root / "quick4_contact_sheet.png"),
                        "uiReviewHtml": str(review_root / "UIreview.html"),
                        "uiVideo": str(review_root / "uitest-videos" / "run.mp4"),
                        "uiVideoIdentity": {
                            "runID": "run-1",
                            "file": "run.mp4",
                            "sha256": hashlib.sha256(b"video").hexdigest(),
                        },
                },
            }
        ),
        encoding="utf-8",
    )
    (evidence / "artifacts" / "ui-evidence-contract.json").write_text(
        json.dumps(
            {
                "valid": True,
                "stepCount": 6,
                "stepSha256": [hashlib.sha256(ONE_BY_ONE_PNG).hexdigest()] * 6,
                "contactSheet": png_metadata(review_root / "contact_sheet.png"),
                "quick4Sheet": png_metadata(review_root / "quick4_contact_sheet.png"),
                "videoByteSize": len(b"video"),
                "videoSha256": hashlib.sha256(b"video").hexdigest(),
                "reviewHtmlSha256": hashlib.sha256(b"KG UITest Run Review").hexdigest(),
                "provenance": {
                    "sourceCommit": "commit-1",
                    "datasetID": "dataset-1",
                    "datasetSHA256": dataset_sha256,
                    "device": "UDID-1",
                    "selector": "--method Example/testExample",
                    "variant": "dataset:dataset-1+profile:standard",
                },
            }
        ),
        encoding="utf-8",
    )
    (review_root / "review_manifest.json").write_text(
        json.dumps(
            {
                "schema": "kg.visual-review.manifest.v1",
                "source": "uitest",
                "provenance": {
                    "sourceCommit": "commit-1",
                    "datasetID": "dataset-1",
                    "datasetSHA256": dataset_sha256,
                    "device": "UDID-1",
                    "selector": "--method Example/testExample",
                    "variant": "dataset:dataset-1+profile:standard",
                },
                "items": [
                    {"assetID": "01-reader", "relPath": "01-reader.png", "stateLabel": "reader"},
                    {"assetID": "02-toc-open", "relPath": "02-toc-open.png", "stateLabel": "toc-open"},
                    {"assetID": "03-chapter-select", "relPath": "03-chapter-select.png", "stateLabel": "chapter-select"},
                    {"assetID": "04-navigation-result", "relPath": "04-navigation-result.png", "stateLabel": "navigation-result"},
                    {"assetID": "05-navigation-failure", "relPath": "05-navigation-failure.png", "stateLabel": "navigation-failure"},
                    {"assetID": "06-missing-chapter", "relPath": "06-missing-chapter.png", "stateLabel": "missing-chapter"},
                ]
            }
        ),
        encoding="utf-8",
    )
    manifest = json.loads((review_root / "review_manifest.json").read_text())
    for item in manifest["items"]:
        item.update(png_metadata(review_root / item["relPath"]))
        item["surface"] = "UITest Step"
        item["lane"] = "ui-test"
        item["stateFacet"] = "step"
    (review_root / "review_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    manifest_sha = hashlib.sha256((review_root / "review_manifest.json").read_bytes()).hexdigest()
    (review_root / "review_state.json").write_text(
        json.dumps(
            {
                "schema": "kg.ui.review-state.v2",
                "entries": [
                    {
                        "reviewer": "codex",
                        "status": "pass",
                        "observedAt": "2026-08-13T00:00:00+00:00",
                        "assetIDs": [
                            "01-reader", "02-toc-open", "03-chapter-select",
                            "04-navigation-result", "05-navigation-failure", "06-missing-chapter",
                        ],
                        "visualChecks": ["chapter hierarchy", "selection/loading state"],
                        "notes": "checked all steps",
                        "manifestSHA256": manifest_sha,
                        "evidenceRootSHA256": evidence_root_sha256(review_root, manifest),
                        "provenance": manifest["provenance"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    (tmp_path / ".gitignore").write_text("build/\nops/\n", encoding="utf-8")
    (tmp_path / "source.txt").write_text("source\n", encoding="utf-8")
    verdict_path = evidence / "verdict.json"
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Test"],
        check=True,
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", ".gitignore", "source.txt"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "source"], check=True)
    source_commit = subprocess.check_output(
        ["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True
    ).strip()

    def replace_source_commit(value: object) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "sourceCommit":
                    value[key] = source_commit
                else:
                    replace_source_commit(child)
        elif isinstance(value, list):
            for child in value:
                replace_source_commit(child)

    for json_path in (
        verdict_path,
        evidence / "artifacts" / "ui-evidence-contract.json",
        review_root / "review_manifest.json",
        review_root / "review_state.json",
    ):
        payload = json.loads(json_path.read_text(encoding="utf-8"))
        replace_source_commit(payload)
        json_path.write_text(json.dumps(payload), encoding="utf-8")
    updated_manifest = json.loads((review_root / "review_manifest.json").read_text(encoding="utf-8"))
    updated_review_state = json.loads((review_root / "review_state.json").read_text(encoding="utf-8"))
    updated_review_state["entries"][-1]["manifestSHA256"] = hashlib.sha256(
        (review_root / "review_manifest.json").read_bytes()
    ).hexdigest()
    updated_review_state["entries"][-1]["evidenceRootSHA256"] = evidence_root_sha256(
        review_root, updated_manifest
    )
    (review_root / "review_state.json").write_text(
        json.dumps(updated_review_state), encoding="utf-8"
    )

    _, verification = MODULE.record_requirement(
        data,
        requirement_id="P3",
        status="verified",
        root=tmp_path,
        selector="Example/testExample",
        dataset_id="dataset-1",
        run_id="run-1",
        evidence_root="build/snapshots/uitest-evidence/run-1",
    )

    assert verification["status"] == "verified"
    assert verification["sourceCommit"] == source_commit
    assert verification["device"] == "UDID-1"
    assert verification["history"][-1]["runID"] == "run-1"

    verdict_path = evidence / "verdict.json"
    original_verdict = verdict_path.read_text(encoding="utf-8")
    verdict = json.loads(original_verdict)
    verdict["options"]["datasetSHA256"] = "wrong-dataset-sha"
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    with pytest.raises(MODULE.UIReviewMatrixError, match="datasetSHA256"):
        MODULE._evidence_provenance(
            evidence,
            requirement=next(item for item in data["requirements"] if item["id"] == "P3"),
            selector="Example/testExample",
            dataset_id="dataset-1",
            run_id="run-1",
            repository_root=tmp_path,
        )
    verdict_path.write_text(original_verdict, encoding="utf-8")

    review_state_path = review_root / "review_state.json"
    original_review_state = review_state_path.read_text(encoding="utf-8")
    review_state = json.loads(original_review_state)
    review_state["entries"].append({"status": "fail", "notes": "latest retry failed"})
    review_state_path.write_text(json.dumps(review_state), encoding="utf-8")
    with pytest.raises(MODULE.UIReviewMatrixError, match="latest visual attestation"):
        MODULE._evidence_provenance(
            evidence,
            requirement=next(item for item in data["requirements"] if item["id"] == "P3"),
            selector="Example/testExample",
            dataset_id="dataset-1",
            run_id="run-1",
            repository_root=tmp_path,
        )
    review_state_path.write_text(original_review_state, encoding="utf-8")

    p3_requirement = next(item for item in data["requirements"] if item["id"] == "P3")
    original_counterexamples = list(p3_requirement["verification"]["counterexampleSteps"])
    p3_requirement["verification"]["counterexampleSteps"] = ["reader", "missing-chapter"]
    with pytest.raises(MODULE.UIReviewMatrixError, match="disjoint assets"):
        MODULE._evidence_provenance(
            evidence,
            requirement=p3_requirement,
            selector="Example/testExample",
            dataset_id="dataset-1",
            run_id="run-1",
            repository_root=tmp_path,
        )
    p3_requirement["verification"]["counterexampleSteps"] = original_counterexamples

    (review_root / "01-reader.png").write_bytes(b"tampered")
    with pytest.raises(MODULE.UIReviewMatrixError, match="not a PNG|step hashes"):
        MODULE._evidence_provenance(
            evidence,
            requirement=next(item for item in data["requirements"] if item["id"] == "P3"),
            selector="Example/testExample",
            dataset_id="dataset-1",
            run_id="run-1",
            repository_root=tmp_path,
        )

    (review_root / "01-reader.png").write_bytes(ONE_BY_ONE_PNG)
    (review_root / "uitest-videos" / "run.mp4").write_bytes(b"xxxxx")
    with pytest.raises(
        MODULE.UIReviewMatrixError,
        match="video identity sha256 mismatch|videoSha256",
    ):
        MODULE._evidence_provenance(
            evidence,
            requirement=next(item for item in data["requirements"] if item["id"] == "P3"),
            selector="Example/testExample",
            dataset_id="dataset-1",
            run_id="run-1",
            repository_root=tmp_path,
        )

    (review_root / "uitest-videos" / "run.mp4").write_bytes(b"video")
    (review_root / "UIreview.html").write_text("KG UITest Run Review!", encoding="utf-8")
    with pytest.raises(MODULE.UIReviewMatrixError, match="reviewHtmlSha256"):
        MODULE._evidence_provenance(
            evidence,
            requirement=next(item for item in data["requirements"] if item["id"] == "P3"),
            selector="Example/testExample",
            dataset_id="dataset-1",
            run_id="run-1",
            repository_root=tmp_path,
        )


def test_dirty_git_tree_is_detected(tmp_path: Path) -> None:
    import subprocess as subprocess_module

    repo = tmp_path / "dirty-tree"
    repo.mkdir()
    subprocess_module.run(["git", "init", "-q", str(repo)], check=True)
    subprocess_module.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    subprocess_module.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "tracked.txt").write_text("clean", encoding="utf-8")
    subprocess_module.run(["git", "-C", str(repo), "add", "tracked.txt"], check=True)
    subprocess_module.run(["git", "-C", str(repo), "commit", "-qm", "test"], check=True)
    assert MODULE._git_source_tree_dirty(repo) is False
    nested = repo / "nested"
    nested.mkdir()
    assert MODULE._git_source_tree_dirty(nested) is False
    (repo / "tracked.txt").write_text("dirty", encoding="utf-8")
    assert MODULE._git_source_tree_dirty(repo) is True
    assert MODULE._git_source_tree_dirty(nested) is True


def test_source_commit_accepts_evidence_receipt_and_rejects_code_drift(tmp_path: Path) -> None:
    repo = tmp_path / "receipt-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
    )
    (repo / "source.txt").write_text("source\n", encoding="utf-8")
    matrix = repo / "ops" / "fixtures" / "ios_ui_review_matrix.json"
    matrix.parent.mkdir(parents=True)
    matrix.write_text("{\"version\": 1}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "source"], check=True)
    source_commit = subprocess.check_output(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
    ).strip()

    matrix.write_text("{\"version\": 2}\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", str(matrix)], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "matrix receipt"], check=True)
    assert MODULE._git_source_commit_matches_current_or_evidence_receipt(repo, source_commit)

    report = repo / "IOS2.0.1+7-UI-review-report" / "CURRENT-STATUS-2026-08-13.md"
    report.parent.mkdir(parents=True)
    report.write_text("receipt\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", str(report)], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "report receipt"], check=True)
    assert MODULE._git_source_commit_matches_current_or_evidence_receipt(repo, source_commit)

    (repo / "source.txt").write_text("drift\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", str(repo / "source.txt")], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "code drift"], check=True)
    assert not MODULE._git_source_commit_matches_current_or_evidence_receipt(repo, source_commit)


def test_source_commit_rejects_unverifiable_non_git_root(tmp_path: Path) -> None:
    assert not MODULE._git_source_commit_matches_current_or_evidence_receipt(
        tmp_path,
        "synthetic-source-commit",
    )


def test_evidence_root_symlink_cannot_escape_repository(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    (root / "build" / "snapshots").mkdir(parents=True)
    outside.mkdir()
    (root / "build" / "snapshots" / "uitest-evidence").symlink_to(
        outside, target_is_directory=True
    )

    with pytest.raises(MODULE.UIReviewMatrixError, match="outside repository root"):
        MODULE._resolve_rooted_path(
            "build/snapshots/uitest-evidence/run-1",
            root=root,
            owner="--evidence-root",
        )


def test_dataset_filename_must_match_internal_dataset_id(tmp_path: Path) -> None:
    dataset_directory = tmp_path / "ops" / "fixtures" / "ui_worlds"
    dataset_directory.mkdir(parents=True)
    dataset = json.loads(
        (ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json").read_text()
    )
    (dataset_directory / "alias.json").write_text(json.dumps(dataset), encoding="utf-8")

    with pytest.raises(MODULE.UIReviewMatrixError, match="filename/id mismatch"):
        MODULE._fixture_ids_for_dataset(root=tmp_path, dataset_id="alias")


def test_report_and_source_paths_cannot_escape_repository(tmp_path: Path) -> None:
    data = MODULE.load_matrix(MATRIX)
    data["report"]["directory"] = str(tmp_path / "outside-report")
    with pytest.raises(MODULE.UIReviewMatrixError, match="inside repository root|outside repository root"):
        MODULE.validate_matrix(data, root=ROOT)

    data = MODULE.load_matrix(MATRIX)
    report_dir = tmp_path / "report"
    report_dir.mkdir()
    source_ref = tmp_path / "source.swift"
    source_ref.write_text("// fixture source\n", encoding="utf-8")
    for requirement in data["requirements"]:
        requirement["sourceRefs"] = [source_ref.name]
    for image in data["report"]["images"]:
        (report_dir / image).write_bytes(
            (ROOT / data["report"]["directory"] / image).read_bytes()
        )
    data["report"]["directory"] = report_dir.name
    outside_image = tmp_path.parent / f"{tmp_path.name}-outside.png"
    outside_image.write_bytes((report_dir / "p1.PNG").read_bytes())
    (report_dir / "p1.PNG").unlink()
    (report_dir / "p1.PNG").symlink_to(outside_image)
    with pytest.raises(MODULE.UIReviewMatrixError, match="report image resolves outside"):
        MODULE.validate_matrix(data, root=tmp_path)

    data = MODULE.load_matrix(MATRIX)
    data["requirements"][0]["sourceRefs"][0] = str(tmp_path / "outside.swift")
    with pytest.raises(MODULE.UIReviewMatrixError, match="inside repository root|outside repository root"):
        MODULE.validate_matrix(data, root=ROOT)


def test_dataset_directory_symlink_cannot_escape_repository(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside-ui-worlds"
    (root / "ops" / "fixtures").mkdir(parents=True)
    outside.mkdir()
    (outside / "alias.json").write_text(
        (ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json").read_text(),
        encoding="utf-8",
    )
    (root / "ops" / "fixtures" / "ui_worlds").symlink_to(outside, target_is_directory=True)

    with pytest.raises(MODULE.UIReviewMatrixError, match="directory resolves outside"):
        MODULE._fixture_ids_for_dataset(root=root, dataset_id="alias")
