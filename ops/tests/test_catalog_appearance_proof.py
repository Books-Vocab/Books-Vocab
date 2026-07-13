from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


proof_module = load_module(
    "catalog_appearance_proof",
    ROOT / "ops" / "catalog_appearance_proof.py",
)


SOURCE_COMMIT = "a" * 40
DATASET_SHA256 = "b" * 64
FIXED_CLOCK = "2026-07-09T14:59:59Z"


def valid_proof() -> dict:
    return {
        "schema": "kg.catalog.appearance.v1",
        "verdict": {"status": "pass", "proofCount": 2},
        "sourceCommit": SOURCE_COMMIT,
        "datasetID": "marketing-account",
        "datasetSHA256": DATASET_SHA256,
        "fixedClock": FIXED_CLOCK,
        "observedAt": "2026-07-13T09:25:00Z",
        "captures": [
            {
                "id": "reader-light",
                "requestedAppearance": "light",
                "actualAppearance": "light",
                "pixelSHA256": "1" * 64,
            },
            {
                "id": "reader-dark",
                "requestedAppearance": "dark",
                "actualAppearance": "dark",
                "pixelSHA256": "2" * 64,
            },
        ],
    }


def validate(proof: dict, **overrides):
    expected = {
        "source_commit": SOURCE_COMMIT,
        "dataset_id": "marketing-account",
        "dataset_sha256": DATASET_SHA256,
        "fixed_clock": FIXED_CLOCK,
    }
    expected.update(overrides)
    return proof_module.validate_appearance_proof(proof, **expected)


def test_valid_exact_proof_passes():
    result = validate(valid_proof())

    assert result == {"status": "pass", "issues": [], "proofCount": 2}


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda proof: proof.update(schema="wrong"), "appearance.schema"),
        (lambda proof: proof.update(extra=True), "appearance.shape"),
        (lambda proof: proof["verdict"].update(status="fail"), "appearance.verdict"),
        (lambda proof: proof.update(captures=[]), "appearance.verdict"),
        (lambda proof: proof.update(sourceCommit="c" * 40), "appearance.sourceCommit"),
        (lambda proof: proof.update(datasetID="other"), "appearance.datasetID"),
        (lambda proof: proof.update(datasetSHA256="c" * 64), "appearance.datasetSHA256"),
        (lambda proof: proof.update(fixedClock="2026-07-10T00:00:00Z"), "appearance.fixedClock"),
        (
            lambda proof: proof["captures"][0].update(actualAppearance="dark"),
            "appearance.capture.0.appearance",
        ),
        (
            lambda proof: proof["captures"][0].update(pixelSHA256="not-a-hash"),
            "appearance.capture.0.pixel-sha256",
        ),
        (
            lambda proof: proof["captures"][0].update(extra=True),
            "appearance.capture.0.shape",
        ),
        (
            lambda proof: proof["captures"][1].update(id="reader-light"),
            "appearance.capture-ids",
        ),
        (
            lambda proof: proof["captures"][0].update(id="light|reader/path.png"),
            "appearance.capture.0.id",
        ),
    ],
)
def test_proof_is_fail_closed(mutate, code: str):
    proof = valid_proof()
    mutate(proof)

    result = validate(proof)

    assert result["status"] == "block"
    assert code in [issue["code"] for issue in result["issues"]]


def test_load_proof_blocks_missing_and_invalid_json(tmp_path: Path):
    missing = proof_module.load_and_validate_appearance_proof(
        tmp_path / "missing.json",
        source_commit=SOURCE_COMMIT,
        dataset_id="marketing-account",
        dataset_sha256=DATASET_SHA256,
        fixed_clock=FIXED_CLOCK,
    )
    invalid_path = tmp_path / "invalid.json"
    invalid_path.write_text("{", encoding="utf-8")
    invalid = proof_module.load_and_validate_appearance_proof(
        invalid_path,
        source_commit=SOURCE_COMMIT,
        dataset_id="marketing-account",
        dataset_sha256=DATASET_SHA256,
        fixed_clock=FIXED_CLOCK,
    )

    assert missing["issues"][0]["code"] == "appearance.missing"
    assert invalid["issues"][0]["code"] == "appearance.invalid"


def test_app_review_gate_imports_shared_contract():
    source = (ROOT / "ops" / "app_review_gate.py").read_text(encoding="utf-8")

    assert "from catalog_appearance_proof import" in source
    assert "validate_appearance_proof" in source
