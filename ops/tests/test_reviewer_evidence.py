from __future__ import annotations

import importlib.util
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "reviewer_evidence", ROOT / "ops" / "reviewer_evidence.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

sys.path.insert(0, str(ROOT / "ops"))
import capture_profile as CAPTURE_PROFILE  # noqa: E402

EvidenceError = MODULE.EvidenceError
build_manifest = MODULE.build_manifest
canonical_manifest_bytes = MODULE.canonical_manifest_bytes
read_build_tuple = MODULE.read_build_tuple
write_bundle = MODULE.write_bundle
validate_promotion_manifest = MODULE.validate_promotion_manifest


def _validate_profile_semantics(path: Path) -> None:
    CAPTURE_PROFILE.load_profile(path)


def _validate_dataset_semantics(path: Path) -> None:
    CAPTURE_PROFILE.validate_fixture_dataset_file(path)


def _fixture(tmp_path: Path) -> dict[str, object]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    profile = tmp_path / "profile.json"
    profile_document = json.loads(
        (ROOT / "ops" / "capture_profiles" / "marketing_demo.json").read_text(
            encoding="utf-8"
        )
    )
    profile_document["id"] = "review-fixed"
    profile.write_text(
        json.dumps(profile_document),
        encoding="utf-8",
    )
    dataset = tmp_path / "ui_world.json"
    dataset_document = json.loads(
        (ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json").read_text(
            encoding="utf-8"
        )
    )
    dataset_document["datasetID"] = "review-fixed"
    dataset.write_text(
        json.dumps(dataset_document),
        encoding="utf-8",
    )
    project = tmp_path / "project.pbxproj"
    project.write_text(
        "MARKETING_VERSION = 2.0.0;\nCURRENT_PROJECT_VERSION = 6;\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "rendered"
    output_dir.mkdir()
    (output_dir / "final_01_graph.png").write_bytes(b"png-graph")
    (output_dir / "final_02_review.png").write_bytes(b"png-review")
    render_spec = {
        "variant": "app-store",
        "target": "promotion",
        "sourceMode": "snapshot-derived",
        "shots": [
            {
                "id": "graph",
                "sourceScenario": "Knowledge Graph View/Populated graph",
                "appearance": "light",
                "outputName": "final_01_graph.png",
                "copy": {"title": "Graph", "subtitle": "Connected"},
            },
            {
                "id": "review",
                "sourceScenario": "Today Review/Back",
                "appearance": "light",
                "outputName": "final_02_review.png",
                "copy": {"title": "Review", "subtitle": "Remember"},
            },
        ],
    }
    profile_digest = hashlib.sha256(profile.read_bytes()).hexdigest()
    dataset_digest = hashlib.sha256(dataset.read_bytes()).hexdigest()
    render_digest = hashlib.sha256(
        json.dumps(render_spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    promotion_manifest = tmp_path / "promotion_manifest.json"
    promotion_manifest.write_text(
        json.dumps(
            {
                "schema": "kg.app_review.promotion_manifest.v1",
                "profileID": "review-fixed",
                "profileSHA256": profile_digest,
                "datasetSHA256": dataset_digest,
                "renderSpecSHA256": render_digest,
                "shots": [
                    {
                        "id": shot["id"],
                        "outputName": shot["outputName"],
                        "appearance": shot["appearance"],
                        "status": "verified",
                        "byteSize": (output_dir / shot["outputName"]).stat().st_size,
                        "sha256": hashlib.sha256(
                            (output_dir / shot["outputName"]).read_bytes()
                        ).hexdigest(),
                    }
                    for shot in render_spec["shots"]
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return {
        "profile_file": profile,
        "profile_id": "review-fixed",
        "dataset_file": dataset,
        "project_file": project,
        "render_output_dir": output_dir,
        "render_spec": render_spec,
        "promotion_manifest_file": promotion_manifest,
        "device_destination": "platform=iOS Simulator,name=iPhone 17 Pro Max",
        "locale": "zh-Hant",
        "fixed_clock": "2026-07-13T09:30:00+08:00",
        "source_commit": "a" * 40,
        "generator_files": [ROOT / "ops" / "capture_profile.py"],
        "profile_validator": _validate_profile_semantics,
        "dataset_validator": _validate_dataset_semantics,
    }


def test_manifest_pins_reviewer_contract_and_is_byte_stable(tmp_path: Path):
    inputs = _fixture(tmp_path)

    first = build_manifest(**inputs)
    second = build_manifest(**inputs)

    assert canonical_manifest_bytes(first) == canonical_manifest_bytes(second)
    assert first["schema"] == "kg.app_review.submission.v1"
    assert first["verdict"]["status"] == "pass"
    assert {item["status"] for item in first["verdict"]["requiredEvidence"]} == {"verified"}
    assert first["build"] == {
        "marketingVersion": "2.0.0",
        "buildNumber": "6",
        "project": {
            "path": "inputs/project.pbxproj",
            "sha256": MODULE.sha256_file(inputs["project_file"]),
        },
    }
    assert first["source"]["commit"] == "a" * 40
    capture = first["capture"]
    assert capture["profile"]["id"] == "review-fixed"
    assert capture["profile"]["sha256"] == MODULE.sha256_file(inputs["profile_file"])
    assert capture["dataset"]["id"] == "review-fixed"
    assert capture["dataset"]["sha256"] == MODULE.sha256_file(inputs["dataset_file"])
    assert capture["fixedClock"] == "2026-07-13T09:30:00+08:00"
    assert capture["locale"] == "zh-Hant"
    assert capture["device"]["destination"].endswith("iPhone 17 Pro Max")
    assert capture["renderSpec"]["sha256"]
    assert capture["renderSpec"]["value"] == inputs["render_spec"]
    assert capture["promotionManifest"]["sha256"] == MODULE.sha256_file(
        inputs["promotion_manifest_file"]
    )
    assert [item["shotID"] for item in first["outputs"]] == ["graph", "review"]
    assert all(item["sha256"] and item["byteSize"] > 0 for item in first["outputs"])
    assert first["provenance"]["sourceCommit"] == "a" * 40
    assert first["provenance"]["rebuild"]["entrypoint"] == "ops/capture_profile.py"


def test_write_bundle_is_atomic_and_reproducible_across_destinations(tmp_path: Path):
    inputs = _fixture(tmp_path)
    manifest = build_manifest(**inputs)

    one = tmp_path / "bundle-one"
    two = tmp_path / "bundle-two"
    write_bundle(
        manifest,
        bundle_dir=one,
        profile_file=inputs["profile_file"],
        dataset_file=inputs["dataset_file"],
        project_file=inputs["project_file"],
        promotion_manifest_file=inputs["promotion_manifest_file"],
        render_output_dir=inputs["render_output_dir"],
        profile_validator=inputs["profile_validator"],
        dataset_validator=inputs["dataset_validator"],
    )
    write_bundle(
        manifest,
        bundle_dir=two,
        profile_file=inputs["profile_file"],
        dataset_file=inputs["dataset_file"],
        project_file=inputs["project_file"],
        promotion_manifest_file=inputs["promotion_manifest_file"],
        render_output_dir=inputs["render_output_dir"],
        profile_validator=inputs["profile_validator"],
        dataset_validator=inputs["dataset_validator"],
    )

    assert (one / "manifest.json").read_bytes() == (two / "manifest.json").read_bytes()
    assert (one / "inputs" / "capture_profile.json").read_bytes() == inputs["profile_file"].read_bytes()
    assert (one / "inputs" / "ui_world.json").read_bytes() == inputs["dataset_file"].read_bytes()
    assert (one / "inputs" / "promotion_manifest.json").read_bytes() == inputs[
        "promotion_manifest_file"
    ].read_bytes()
    assert (one / "outputs" / "final_01_graph.png").read_bytes() == b"png-graph"
    with pytest.raises(EvidenceError, match="已存在"):
        write_bundle(
            manifest,
            bundle_dir=one,
            profile_file=inputs["profile_file"],
            dataset_file=inputs["dataset_file"],
            project_file=inputs["project_file"],
            promotion_manifest_file=inputs["promotion_manifest_file"],
            render_output_dir=inputs["render_output_dir"],
            profile_validator=inputs["profile_validator"],
            dataset_validator=inputs["dataset_validator"],
        )


def test_current_legacy_four_shot_manifest_is_rejected_for_new_five_shot_profile():
    profile = json.loads(
        (ROOT / "ops" / "capture_profiles" / "marketing_account.json").read_text(encoding="utf-8")
    )
    render_spec = {
        "variant": profile["render"]["variant"],
        "target": profile["render"]["target"],
        "sourceMode": profile["render"]["sourceMode"],
        "shots": [
            {
                "id": shot["id"],
                "sourceScenario": shot["sourceScenario"],
                "appearance": shot["appearance"],
                "outputName": shot["outputName"],
                "copy": shot["copy"],
            }
            for shot in profile["shots"]
        ],
    }
    with pytest.raises(EvidenceError, match="legacy|schema|JSON"):
        validate_promotion_manifest(
            ROOT / "promotion" / "screenshots" / "manifest.yml",
            profile_id="marketing_account",
            profile_digest="a" * 64,
            dataset_digest="b" * 64,
            render_spec=render_spec,
            render_output_dir=ROOT / "promotion" / "screenshots" / "dist" / "app-store" / "iphone",
        )
    assert len(profile["shots"]) == 5
    assert len(
        [
            line
            for line in (ROOT / "promotion" / "screenshots" / "manifest.yml").read_text().splitlines()
            if line.lstrip().startswith("- id:")
        ]
    ) == 4


@pytest.mark.parametrize("required_status", ["unknown", "skipped", "stale"])
def test_required_promotion_evidence_never_passes_unverified_status(
    tmp_path: Path, required_status: str
):
    inputs = _fixture(tmp_path)
    manifest_path = inputs["promotion_manifest_file"]
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["shots"][0]["status"] = required_status
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(EvidenceError, match=required_status):
        build_manifest(**inputs)


def test_profile_manifest_outputs_are_exact_closed_world(tmp_path: Path):
    inputs = _fixture(tmp_path)
    manifest_path = inputs["promotion_manifest_file"]
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["shots"].pop()
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(EvidenceError, match="closure"):
        build_manifest(**inputs)


def test_bundle_rehashes_staged_bytes_before_publish(monkeypatch, tmp_path: Path):
    inputs = _fixture(tmp_path)
    manifest = build_manifest(**inputs)
    real_copy = MODULE.shutil.copyfile
    mutated = False

    def mutate_during_first_copy(source, destination):
        nonlocal mutated
        result = real_copy(source, destination)
        if not mutated:
            mutated = True
            Path(destination).write_bytes(b"mutated-after-copy")
        return result

    monkeypatch.setattr(MODULE.shutil, "copyfile", mutate_during_first_copy)
    bundle = tmp_path / "bundle"
    with pytest.raises(EvidenceError, match="staged|漂移"):
        write_bundle(
            manifest,
            bundle_dir=bundle,
            profile_file=inputs["profile_file"],
            dataset_file=inputs["dataset_file"],
            project_file=inputs["project_file"],
            promotion_manifest_file=inputs["promotion_manifest_file"],
            render_output_dir=inputs["render_output_dir"],
            profile_validator=inputs["profile_validator"],
            dataset_validator=inputs["dataset_validator"],
        )
    assert not bundle.exists()
    assert not list(tmp_path.glob(".bundle.tmp-*"))


def test_bundle_copy_failure_cleans_staging(monkeypatch, tmp_path: Path):
    inputs = _fixture(tmp_path)
    manifest = build_manifest(**inputs)

    def fail_copy(*_args, **_kwargs):
        raise OSError("injected copy failure")

    monkeypatch.setattr(MODULE.shutil, "copyfile", fail_copy)
    bundle = tmp_path / "bundle"
    with pytest.raises(OSError, match="injected"):
        write_bundle(
            manifest,
            bundle_dir=bundle,
            profile_file=inputs["profile_file"],
            dataset_file=inputs["dataset_file"],
            project_file=inputs["project_file"],
            promotion_manifest_file=inputs["promotion_manifest_file"],
            render_output_dir=inputs["render_output_dir"],
            profile_validator=inputs["profile_validator"],
            dataset_validator=inputs["dataset_validator"],
        )
    assert not bundle.exists()
    assert not list(tmp_path.glob(".bundle.tmp-*"))


def test_manifest_fails_closed_on_missing_or_unsafe_outputs(tmp_path: Path):
    inputs = _fixture(tmp_path)
    (inputs["render_output_dir"] / "final_02_review.png").unlink()
    with pytest.raises(EvidenceError, match="缺少 reviewer output"):
        build_manifest(**inputs)

    inputs = _fixture(tmp_path / "unsafe")
    inputs["render_spec"]["shots"][0]["outputName"] = "../escape.png"
    with pytest.raises(EvidenceError, match="安全檔名"):
        build_manifest(**inputs)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("source_commit", "HEAD", "40 位"),
        ("fixed_clock", "2026-07-13", "時區"),
        ("locale", "zh Hant", "locale"),
    ],
)
def test_manifest_rejects_unpinned_identity_fields(
    tmp_path: Path, field: str, value: str, message: str
):
    inputs = _fixture(tmp_path)
    inputs[field] = value
    with pytest.raises(EvidenceError, match=message):
        build_manifest(**inputs)


def test_read_build_tuple_requires_one_actual_tuple(tmp_path: Path):
    project = tmp_path / "project.pbxproj"
    project.write_text(
        "MARKETING_VERSION = 2.0.0;\nCURRENT_PROJECT_VERSION = 6;\n",
        encoding="utf-8",
    )
    assert read_build_tuple(project) == ("2.0.0", "6")

    project.write_text("MARKETING_VERSION = 2.0.0;\n", encoding="utf-8")
    with pytest.raises(EvidenceError, match="build tuple"):
        read_build_tuple(project)


def test_manifest_checks_expected_tuple_on_its_authoritative_project_read(tmp_path: Path):
    inputs = _fixture(tmp_path)
    inputs["expected_marketing_version"] = "2.0.0"
    inputs["expected_build_number"] = "6"
    assert read_build_tuple(inputs["project_file"]) == ("2.0.0", "6")
    inputs["project_file"].write_text(
        "MARKETING_VERSION = 9.9.9;\nCURRENT_PROJECT_VERSION = 99;\n",
        encoding="utf-8",
    )

    with pytest.raises(EvidenceError, match="marketing version.*expected=2.0.0 actual=9.9.9"):
        build_manifest(**inputs)


def test_manifest_revalidates_dataset_after_a_precheck_then_swap(tmp_path: Path):
    inputs = _fixture(tmp_path)
    _validate_dataset_semantics(inputs["dataset_file"])
    swapped = json.loads(inputs["dataset_file"].read_text(encoding="utf-8"))
    swapped.pop("auth")
    inputs["dataset_file"].write_text(json.dumps(swapped), encoding="utf-8")

    with pytest.raises(EvidenceError, match="UI World 完整語意驗證失敗"):
        build_manifest(**inputs)


def test_bundle_reruns_full_semantic_validators_on_staged_inputs(tmp_path: Path):
    inputs = _fixture(tmp_path)
    manifest = build_manifest(**inputs)
    staged_paths: dict[str, Path] = {}

    def validate_staged_profile(path: Path) -> None:
        staged_paths["profile"] = path
        _validate_profile_semantics(path)

    def validate_staged_dataset(path: Path) -> None:
        staged_paths["dataset"] = path
        _validate_dataset_semantics(path)

    bundle = tmp_path / "bundle"
    write_bundle(
        manifest,
        bundle_dir=bundle,
        profile_file=inputs["profile_file"],
        dataset_file=inputs["dataset_file"],
        project_file=inputs["project_file"],
        promotion_manifest_file=inputs["promotion_manifest_file"],
        render_output_dir=inputs["render_output_dir"],
        profile_validator=validate_staged_profile,
        dataset_validator=validate_staged_dataset,
    )

    assert staged_paths["profile"].name == "capture_profile.json"
    assert staged_paths["dataset"].name == "ui_world.json"
    assert staged_paths["profile"].parent.name == "inputs"
    assert staged_paths["dataset"].parent.name == "inputs"


def _reviewer_evidence_cli_world(tmp_path: Path) -> dict[str, Path | str]:
    """Everything `capture_profile.py reviewer-evidence` needs except the project file.

    Shared by the two CLI tests so that the one which omits ``--project-file``
    differs from the one that passes it in exactly that argument.
    """
    profile = ROOT / "ops" / "capture_profiles" / "marketing_demo.json"
    dataset = ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json"
    project = tmp_path / "project.pbxproj"
    project.write_text(
        "MARKETING_VERSION = 2.0.0;\nCURRENT_PROJECT_VERSION = 6;\n",
        encoding="utf-8",
    )
    outputs = tmp_path / "rendered"
    outputs.mkdir()
    profile_doc = json.loads(profile.read_text(encoding="utf-8"))
    for shot in profile_doc["shots"]:
        (outputs / shot["outputName"]).write_bytes(f"png:{shot['id']}".encode())
    bundle = tmp_path / "bundle"
    promotion_manifest = tmp_path / "promotion_manifest.json"
    render_spec = {
        "variant": profile_doc["render"]["variant"],
        "target": profile_doc["render"]["target"],
        "sourceMode": profile_doc["render"]["sourceMode"],
        "shots": [
            {
                "id": shot["id"], "sourceScenario": shot["sourceScenario"],
                "appearance": shot["appearance"], "outputName": shot["outputName"],
                "copy": shot["copy"],
            }
            for shot in profile_doc["shots"]
        ],
    }
    promotion_manifest.write_text(
        json.dumps({
            "schema": "kg.app_review.promotion_manifest.v1",
            "profileID": profile_doc["id"],
            "profileSHA256": hashlib.sha256(profile.read_bytes()).hexdigest(),
            "datasetSHA256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "renderSpecSHA256": hashlib.sha256(json.dumps(
                render_spec, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()).hexdigest(),
            "shots": [{
                "id": shot["id"], "outputName": shot["outputName"],
                "appearance": shot["appearance"], "status": "verified",
                "byteSize": (outputs / shot["outputName"]).stat().st_size,
                "sha256": hashlib.sha256((outputs / shot["outputName"]).read_bytes()).hexdigest(),
            } for shot in render_spec["shots"]],
        }), encoding="utf-8")
    source_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True
    ).stdout.strip()
    return {
        "profile": profile,
        "dataset": dataset,
        "project": project,
        "outputs": outputs,
        "bundle": bundle,
        "promotion_manifest": promotion_manifest,
        "source_commit": source_commit,
    }


def _run_reviewer_evidence_cli(world: dict, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "capture_profile.py"),
            "reviewer-evidence",
            str(world["profile"]),
            "--dataset-file",
            str(world["dataset"]),
            "--render-output-dir",
            str(world["outputs"]),
            "--promotion-manifest",
            str(world["promotion_manifest"]),
            "--bundle-dir",
            str(world["bundle"]),
            "--source-commit",
            str(world["source_commit"]),
            "--fixed-clock",
            "2026-07-13T09:30:00+08:00",
            "--locale",
            "zh-Hant",
            *extra,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_capture_profile_reviewer_evidence_dry_run_writes_nothing(tmp_path: Path):
    world = _reviewer_evidence_cli_world(tmp_path)
    project, bundle = world["project"], world["bundle"]

    result = _run_reviewer_evidence_cli(
        world,
        "--project-file",
        str(project),
        "--expect-marketing-version",
        "2.0.0",
        "--expect-build-number",
        "6",
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["schema"] == "kg.capture.run.v1"
    assert payload["action"] == "reviewer-evidence"
    assert payload["status"] == "dry-run"
    assert payload["manifest"]["schema"] == "kg.app_review.submission.v1"
    assert payload["manifest"]["build"]["marketingVersion"] == "2.0.0"
    assert not bundle.exists()


def test_reviewer_evidence_without_project_file_takes_the_source_commit_blob(tmp_path: Path):
    """The CLI default is the pinned commit's pbxproj, not whatever is checked out.

    Pinned to the *previous* commit that touched the project file, so the blob
    and the checkout necessarily differ: against HEAD the two coincide in a clean
    tree and the test would pass without proving anything.  The expected digest
    comes from ``git cat-file`` here rather than from the tool's own output.
    """
    rel = "ios/BooksAndVocab.xcodeproj/project.pbxproj"
    history = subprocess.run(
        ["git", "log", "--format=%H", "-2", "--", rel],
        cwd=ROOT, text=True, capture_output=True, check=True,
    ).stdout.split()
    if len(history) < 2:
        pytest.skip("needs two commits touching the project file to tell blob from checkout")
    pinned = history[1]
    blob = subprocess.run(
        ["git", "cat-file", "blob", f"{pinned}:{rel}"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout
    assert blob != (ROOT / rel).read_bytes(), "positive control: pinned blob must differ from checkout"

    world = _reviewer_evidence_cli_world(tmp_path) | {"source_commit": pinned}

    result = _run_reviewer_evidence_cli(world)

    assert result.returncode == 0, result.stderr
    manifest = json.loads(result.stdout)["manifest"]
    assert manifest["build"]["project"]["sha256"] == hashlib.sha256(blob).hexdigest()
    assert manifest["source"]["commit"] == pinned
    assert not world["bundle"].exists()


def test_reviewer_evidence_help_is_self_describing():
    result = subprocess.run(
        [sys.executable, str(ROOT / "ops" / "capture_profile.py"), "reviewer-evidence", "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--commit" in result.stdout
    assert "dry-run" in result.stdout
    assert "--fixed-clock" in result.stdout
    assert "--expect-marketing-version" in result.stdout
    assert "--promotion-manifest" in result.stdout
    assert "unknown/skipped/stale" in result.stdout
