from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

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
