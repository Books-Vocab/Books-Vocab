from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = ROOT / "ops" / "demo"


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, DEMO_DIR / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(DEMO_DIR))
    try:
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    finally:
        try:
            sys.path.remove(str(DEMO_DIR))
        except ValueError:
            pass
    return module


sot = _load_module("sot")
emit_ios = _load_module("emit_ios")
build_demo = _load_module("build_demo")


def test_emit_ios_matches_committed_generated_fixture_dataset():
    """Generated iOS UI World must not drift from the emitter."""
    bundle = sot.load_sot()
    [(path, fresh_bytes)] = emit_ios._artifacts(bundle)

    assert path == ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"
    assert path.read_bytes() == fresh_bytes


def test_emit_ios_uses_full_ui_world_manifest_baseline():
    """The emitter must not regress to the old partial empty-domain skeleton."""
    bundle = sot.load_sot()
    [(_, fresh_bytes)] = emit_ios._artifacts(bundle)
    document = json.loads(fresh_bytes)

    assert document["schema"] == "kg.fixture.dataset.v2"
    assert document["datasetID"] == "demo-demo-user"
    assert document["auth"]["signedIn"]["keychainTokenState"] == "available"
    assert document["auth"]["guest"]["keychainTokenState"] == "absent"
    assert document["assets"]["books"]
    assert document["assets"]["audio"]
    assert document["assets"]["subtitles"]
    assert document["assets"]["text"]
    assert document["settings"]
    assert document["bookshelf"]
    assert document["podcast"]
    assert document["runtimePodcast"]
    assert document["reader"]
    assert document["vocabulary"]
    assert document["reviewDeck"]


def test_emit_ios_only_overlays_identity_owned_auth_fields():
    """Generated demo must remain the baseline UI World plus identity overlay."""
    bundle = sot.load_sot()
    baseline = emit_ios._load_base_ui_world()
    [(_, fresh_bytes)] = emit_ios._artifacts(bundle)
    document = json.loads(fresh_bytes)

    for key in emit_ios.FIXTURE_TOP_LEVEL_KEYS - {"datasetID", "auth"}:
        assert document[key] == baseline[key]

    assert set(document["auth"]) == set(baseline["auth"])
    for fixture_key, seed in document["auth"].items():
        if fixture_key != "signedIn":
            assert seed == baseline["auth"][fixture_key]
            continue

        changed = {
            key
            for key, value in seed.items()
            if value != baseline["auth"]["signedIn"][key]
        }
        assert changed <= emit_ios.IDENTITY_OWNED_SIGNED_IN_KEYS
        assert seed["userId"] == bundle.identity["user_id"]
        assert seed["token"] == bundle.identity["access_token"]


def test_emit_ios_rejects_unknown_top_level_key():
    """Swift keyed decoding would ignore this; the emitter must fail first."""
    baseline = emit_ios._load_base_ui_world()
    document = dict(baseline)
    document["datasetID"] = "demo-demo-user"
    document["legacyFixture"] = {}

    with pytest.raises(ValueError, match="invalid top-level keys"):
        emit_ios._validate_fixture_document(document, baseline)


def test_emit_ios_rejects_non_identity_domain_drift():
    baseline = emit_ios._load_base_ui_world()
    document = dict(baseline)
    document["datasetID"] = "demo-demo-user"
    document["bookshelf"] = {}

    with pytest.raises(ValueError, match="only overlay identity-owned auth"):
        emit_ios._validate_fixture_document(document, baseline)


@pytest.mark.parametrize(
    "argv",
    [
        ["--check", "--json", "emit-ios"],
        ["emit-ios", "--check", "--json"],
    ],
)
def test_build_demo_global_flags_work_before_and_after_subcommand(argv, capsys):
    rc = build_demo.main(argv)
    output = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert output["target"] == "emit-ios"
    assert output["check"] is True
    assert output["result"]["action"] == "check"
    assert output["result"]["drift"] is False
