from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("ui_world_manifest", ROOT / "ops" / "ui_world_manifest.py")
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

UIWorldManifestError = MODULE.UIWorldManifestError
validate_fixture_dataset_file = MODULE.validate_fixture_dataset_file


def _marketing_demo() -> dict:
    return json.loads((ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json").read_text(encoding="utf-8"))


def test_validate_accepts_repo_ui_world():
    dataset_id = validate_fixture_dataset_file(ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json")

    assert dataset_id == "marketing_demo"


def test_validate_accepts_all_repo_and_generated_ui_worlds():
    repo_worlds = sorted((ROOT / "ops" / "fixtures" / "ui_worlds").glob("*.json"))
    generated_worlds = [ROOT / "ops" / "demo" / "generated" / "ios_fixture_dataset.json"]
    assert repo_worlds

    dataset_ids = [validate_fixture_dataset_file(path) for path in [*repo_worlds, *generated_worlds]]

    assert "marketing_demo" in dataset_ids
    assert "demo-demo-user" in dataset_ids


def test_validate_rejects_asset_hash_drift(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["sha256"] = "0" * 64
    path = tmp_path / "bad_hash.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="assets.books.catalog_reader_epub.sha256 mismatch"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_zero_byte_asset(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["byteSize"] = 0
    path = tmp_path / "zero_byte.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="byteSize 必須是正整數"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_unknown_asset_property(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["legacyPath"] = "ghost"
    path = tmp_path / "unknown_asset_property.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="keys 不符合 UI World v2"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_preference_wrapper_key(tmp_path: Path):
    data = _marketing_demo()
    del data["preferences"]["ubiquitousKeyValueStore"]
    path = tmp_path / "missing_preference_wrapper.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"preferences keys .*ubiquitousKeyValueStore"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_unknown_preference_wrapper_key(tmp_path: Path):
    data = _marketing_demo()
    data["preferences"]["legacyDefaults"] = {}
    path = tmp_path / "unknown_preference_wrapper.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"preferences keys .*legacyDefaults"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_invalid_preference_value_type(tmp_path: Path):
    data = _marketing_demo()
    data["preferences"]["userDefaults"]["auto_sync_enabled"] = None
    path = tmp_path / "invalid_preference_value.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="preferences.userDefaults.auto_sync_enabled"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_runtime_download_local_path(tmp_path: Path):
    data = _marketing_demo()
    del data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]["localAudioPath"]
    path = tmp_path / "missing_download_local_path.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"download keys .*localAudioPath"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_unknown_runtime_download_key(tmp_path: Path):
    data = _marketing_demo()
    data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]["downloaded"] = True
    path = tmp_path / "unknown_download_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"download keys .*downloaded"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_runtime_download_local_path_drift(tmp_path: Path):
    data = _marketing_demo()
    data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]["localAudioPath"] = "podcast-downloads/wrong.m4a"
    path = tmp_path / "download_local_path_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="localAudioPath must match asset installAs"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_runtime_download_subtitle_path_without_subtitle_ref(tmp_path: Path):
    data = _marketing_demo()
    download = data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]
    download["subtitleAssetRef"] = None
    path = tmp_path / "download_subtitle_path_without_ref.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="localSubtitlePath must be null"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_runtime_download_asset_ref(tmp_path: Path):
    data = _marketing_demo()
    data["runtimePodcast"]["playablePreview"]["episodes"][0]["download"]["audioAssetRef"] = "audio.missing"
    path = tmp_path / "missing_runtime_audio.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="download.audioAssetRef references missing audio.missing"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_auth_state_drift(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["auth"]["email"] = "drift@example.com"
    path = tmp_path / "settings_auth_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="settings.subscription_free.auth.email must match auth.settingsSignedIn.email"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_logged_in_auth_without_user_id(tmp_path: Path):
    data = _marketing_demo()
    data["auth"]["signedIn"]["userId"] = None
    path = tmp_path / "missing_logged_in_user_id.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="auth.signedIn.userId"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_auth_seed_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["auth"]["signedIn"]["providerUserId"]
    path = tmp_path / "missing_nullable_auth_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"auth.signedIn keys .*providerUserId"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_auth_seed_unknown_key(tmp_path: Path):
    data = _marketing_demo()
    data["auth"]["signedIn"]["legacyUserId"] = "user-legacy"
    path = tmp_path / "unknown_auth_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"auth.signedIn keys .*legacyUserId"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_book_install_drift(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["installAs"] = "Books/wrong.epub"
    path = tmp_path / "book_install_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="installAs must be Books/catalog-reader.epub"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_seed_missing_reference_date(tmp_path: Path):
    data = _marketing_demo()
    del data["bookshelf"]["with_books_library"]["referenceDate"]
    path = tmp_path / "bookshelf_missing_reference_date.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"bookshelf.with_books_library keys .*referenceDate"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_book_unknown_row_key(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["with_books_library"]["books"][0]["legacyProgress"] = 0.1
    path = tmp_path / "bookshelf_unknown_book_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"bookshelf.with_books_library.books\[0\] keys .*legacyProgress"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_progression_out_of_range(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["with_books_library"]["books"][0]["progression"] = 1.1
    path = tmp_path / "bookshelf_bad_progression.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"progression must be between 0 and 1"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_invalid_date(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["with_books_library"]["books"][0]["dateAdded"] = "not-a-date"
    path = tmp_path / "bookshelf_bad_date.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"dateAdded must be ISO8601"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_bookshelf_last_read_before_added(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["with_books_library"]["books"][0]["dateAdded"] = "2026-01-06T00:00:00Z"
    data["bookshelf"]["with_books_library"]["books"][0]["dateLastRead"] = "2026-01-05T00:00:00Z"
    path = tmp_path / "bookshelf_last_read_before_added.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"dateLastRead must not be earlier than dateAdded"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_preferred_notebook_ref(tmp_path: Path):
    data = _marketing_demo()
    data["bookshelf"]["reader_notebook_bound"]["books"][0]["preferredNotebookId"] = "missing-nb"
    path = tmp_path / "missing_preferred_notebook.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="preferredNotebookId references missing notebook missing-nb"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_missing_notebook_cover_asset_ref(tmp_path: Path):
    data = _marketing_demo()
    data["notebook"]["coverGallery"]["notebooks"][0]["coverImageAssetRef"] = "images.missing"
    path = tmp_path / "missing_notebook_cover.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="coverImageAssetRef references missing images.missing"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_notebook_sync_status_out_of_range(tmp_path: Path):
    data = _marketing_demo()
    data["notebook"]["populated"]["notebooks"][0]["syncStatus"] = 9
    path = tmp_path / "notebook_bad_sync_status.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"notebook.populated.notebooks\[0\].syncStatus"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_notebook_card_count_drift(tmp_path: Path):
    data = _marketing_demo()
    data["notebook"]["cardGallery"]["notebooks"][0]["cardState"]["cardCount"] = 1
    path = tmp_path / "notebook_card_count_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="cardCount must equal dueCount"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_vocabulary_duplicate_entry_words(tmp_path: Path):
    data = _marketing_demo()
    entry = dict(data["vocabulary"]["vocabLinkedCards"]["entries"][0])
    data["vocabulary"]["vocabLinkedCards"]["entries"].append(entry)
    path = tmp_path / "vocabulary_duplicate_entries.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match="vocabulary.vocabLinkedCards.entries.word must not contain duplicate values"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_vocabulary_review_history_missing_entry_ref(tmp_path: Path):
    data = _marketing_demo()
    data["vocabulary"]["vocabLinkedCards"]["reviewHistory"] = [
        {"word": "missing-word", "feedback": 1, "reviewedAt": "2026-01-01T00:00:00Z"}
    ]
    path = tmp_path / "vocabulary_review_history_missing_entry.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"reviewHistory\[0\].missing-word must reference an entry"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_review_deck_invalid_action_type(tmp_path: Path):
    data = _marketing_demo()
    data["reviewDeck"]["phaseSingle"]["entries"][0]["actionType"] = "merge"
    path = tmp_path / "review_deck_bad_action_type.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"reviewDeck.phaseSingle.entries\[0\].actionType must be add/delete/edit"):
        validate_fixture_dataset_file(path)


def test_cli_prints_dataset_id_for_valid_world():
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "ops" / "ui_world_manifest.py"),
            "validate",
            str(ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "marketing_demo"
