from __future__ import annotations

import importlib.util
import json
import sys
import zipfile
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
    artifacts = dict(emit_ios._artifacts(bundle))
    path = ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"

    assert path.read_bytes() == artifacts[path]


def test_emit_ios_carries_canonical_shared_decks_from_baseline():
    bundle = sot.load_sot()
    baseline = emit_ios._load_base_ui_world()
    generated_path = ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"
    fresh_bytes = dict(emit_ios._artifacts(bundle))[generated_path]
    generated = json.loads(fresh_bytes)

    assert set(baseline["sharedDecks"]) == {"fixtures", "decks"}
    assert generated["sharedDecks"] == baseline["sharedDecks"]
    assert "sharedDecks" not in generated["scenarioContext"].get("surfaceContracts", {})


def test_emit_ios_uses_full_ui_world_manifest_baseline():
    """The emitter must not regress to the old partial empty-domain skeleton."""
    bundle = sot.load_sot()
    generated_path = ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"
    fresh_bytes = dict(emit_ios._artifacts(bundle))[generated_path]
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


def test_dictionary_scenario_contract_is_absent_from_canonical_artifacts():
    bundle = sot.load_sot()
    artifacts = dict(emit_ios._artifacts(bundle))
    marketing_path = ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json"
    generated_path = ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"

    assert set(artifacts) == {marketing_path, generated_path}
    documents = [json.loads(artifacts[path]) for path in (marketing_path, generated_path)]
    contexts = [document["scenarioContext"] for document in documents]
    assert contexts[0] == contexts[1]

    assert set(contexts[0]) == {
        "reviewClock", "readerPassage", "wordDetail", "surfaceContracts",
    }
    assert set(contexts[0]["surfaceContracts"]) == {
        "explore", "reviewCalendar", "settings",
    }


def test_emit_ios_preserves_real_reader_toc_assets():
    bundle = sot.load_sot()
    generated_path = ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"
    fresh_bytes = dict(emit_ios._artifacts(bundle))[generated_path]
    document = json.loads(fresh_bytes)
    books = document["assets"]["books"]

    valid = books["reader_real_book_epub"]
    invalid = books["reader_invalid_destination_epub"]
    for asset in (valid, invalid):
        assert not Path(asset["sourcePath"]).is_absolute()
        path = ROOT / asset["sourcePath"]
        assert path.is_file()
        assert path.stat().st_size == asset["byteSize"]
        assert path.is_relative_to(ROOT)

    with zipfile.ZipFile(ROOT / valid["sourcePath"]) as archive:
        assert "OEBPS/chapter1.xhtml" in archive.namelist()
        assert "OEBPS/chapter2.xhtml" in archive.namelist()
    with zipfile.ZipFile(ROOT / invalid["sourcePath"]) as archive:
        assert "chapter-missing.xhtml" in archive.read("OEBPS/nav.xhtml").decode("utf-8")


def test_emit_ios_rejects_reader_asset_symlink_escape(tmp_path: Path):
    outside = tmp_path / "outside-reader.epub"
    outside.write_bytes(b"outside")
    link = ROOT / "ops" / "fixtures" / "assets" / ".p3-emitter-escape-link"
    document = {
        "assets": {
            "books": {
                "reader_real_book_epub": {"sourcePath": str(link.relative_to(ROOT))},
                "reader_invalid_destination_epub": {
                    "sourcePath": "ops/fixtures/assets/reader-invalid-destination.epub",
                },
            },
            "audio": {},
            "subtitles": {},
            "text": {},
            "images": {},
        }
    }
    try:
        link.symlink_to(outside)
        with pytest.raises(ValueError, match="escapes repo root"):
            emit_ios._normalize_asset_source_paths(document)
    finally:
        if link.is_symlink() or link.exists():
            link.unlink()
def test_emit_ios_keeps_asset_sources_portable_to_current_checkout():
    """The emitter must preserve repo-relative sources for any checkout root."""
    bundle = sot.load_sot()
    artifacts = dict(emit_ios._artifacts(bundle))
    generated_path = ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"
    document = json.loads(artifacts[generated_path])
    current_root = emit_ios._REPO_ROOT.resolve()

    for domain in document["assets"].values():
        for asset in domain.values():
            source = Path(asset["sourcePath"])
            assert not source.is_absolute()
            assert (current_root / source).resolve().is_relative_to(current_root)


def test_emit_ios_validates_generated_manifest_with_shared_validator(monkeypatch):
    bundle = sot.load_sot()
    calls = []

    def fail_validator(path, *, label, **kwargs):
        calls.append((path, label, kwargs))
        raise emit_ios.UIWorldManifestError("shared validator rejected generated demo")

    monkeypatch.setattr(emit_ios, "validate_fixture_dataset_file", fail_validator)

    with pytest.raises(ValueError, match="shared validator rejected generated demo"):
        emit_ios._artifacts(bundle)

    assert calls
    assert calls[0][1] == "Generated demo UI World"
    assert calls[0][2]["require_review_clock"] is True
    assert calls[0][2]["require_review_history_alignment"] is True


def test_emit_ios_only_overlays_identity_owned_auth_fields():
    """Generated demo must remain the baseline UI World plus identity overlay."""
    bundle = sot.load_sot()
    baseline = emit_ios._load_base_ui_world()
    generated_path = ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"
    fresh_bytes = dict(emit_ios._artifacts(bundle))[generated_path]
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


def test_demo_sot_requires_card_notebook(tmp_path):
    dataset = json.loads((DEMO_DIR / "demo_dataset.json").read_text(encoding="utf-8"))
    del dataset["cards"][0]["notebook"]
    path = tmp_path / "demo_dataset_missing_card_notebook.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    with pytest.raises(sot.SoTError, match=r"cards\[0\] missing notebook"):
        sot.load_dataset(path)


def test_demo_sot_requires_link_notebook(tmp_path):
    dataset = json.loads((DEMO_DIR / "demo_dataset.json").read_text(encoding="utf-8"))
    del dataset["links"][0]["notebook"]
    path = tmp_path / "demo_dataset_missing_link_notebook.json"
    path.write_text(json.dumps(dataset), encoding="utf-8")

    with pytest.raises(sot.SoTError, match=r"links\[0\] missing notebook"):
        sot.load_dataset(path)


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
