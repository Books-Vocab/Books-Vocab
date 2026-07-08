from __future__ import annotations

import importlib.util
import json
import re
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


def _swift_fixture_ids(path: str, enum_name: str) -> set[str]:
    source = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(rf"enum {enum_name}: String, CaseIterable \{{(?P<body>.*?)\n\}}", source, flags=re.S)
    assert match, f"missing Swift enum {enum_name}"
    fixture_ids = set()
    for line in match.group("body").splitlines():
        case_match = re.match(r'\s*case\s+(\w+)(?:\s*=\s*"([^"]+)")?', line)
        if case_match:
            fixture_ids.add(case_match.group(2) or case_match.group(1))
    assert fixture_ids, f"missing cases for Swift enum {enum_name}"
    return fixture_ids


def _swift_string_set(path: str, constant_name: str) -> set[str]:
    source = (ROOT / path).read_text(encoding="utf-8")
    match = re.search(rf"static let {constant_name}: Set<String> = \[(?P<body>.*?)\n\s*\]", source, flags=re.S)
    assert match, f"missing Swift Set constant {constant_name}"
    values = set(re.findall(r'"([^"]+)"', match.group("body")))
    assert values, f"missing values for Swift Set constant {constant_name}"
    return values


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


@pytest.mark.parametrize(
    ("domain", "path", "enum_name"),
    [
        ("auth", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift", "UIWorldAuthFixtureID"),
        ("entitlements", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift", "UIWorldEntitlementsFixtureID"),
        ("settings", "ios/BooksAndVocab/Support/Fixtures/Settings/SettingsFixtures.swift", "SettingsFixtureID"),
        ("bookshelf", "ios/BooksAndVocab/Support/Fixtures/Bookshelf/BookshelfFixtures.swift", "BookshelfFixtureID"),
        ("todayReview", "ios/BooksAndVocab/Support/Fixtures/TodayReview/TodayReviewFixtures.swift", "TodayReviewFixtureID"),
        ("notebook", "ios/BooksAndVocab/Support/Fixtures/Notebook/NotebookFixtures.swift", "NotebookFixtureID"),
        ("podcast", "ios/BooksAndVocab/Support/Fixtures/Podcast/PodcastFixtures.swift", "PodcastFixtureID"),
        ("runtimePodcast", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift", "UIWorldRuntimePodcastFixtureID"),
        ("reader", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift", "UIWorldReaderFixtureID"),
        ("vocabulary", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift", "UIWorldVocabularyFixtureID"),
        ("reviewDeck", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift", "UIWorldReviewDeckFixtureID"),
        ("syncPresenter", "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift", "UIWorldSyncPresenterFixtureID"),
    ],
)
def test_fixture_domain_ids_match_swift_fixture_enums(domain: str, path: str, enum_name: str):
    assert MODULE.FIXTURE_DOMAIN_IDS[domain] == _swift_fixture_ids(path, enum_name)


@pytest.mark.parametrize(
    ("domain", "swift_constant"),
    [
        ("userDefaults", "userDefaultsKeys"),
        ("ubiquitousKeyValueStore", "ubiquitousKeyValueStoreKeys"),
    ],
)
def test_preference_domain_keys_match_swift_preferences_seed(domain: str, swift_constant: str):
    swift_path = "ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift"

    assert MODULE.PREFERENCE_DOMAIN_KEYS[domain] == _swift_string_set(swift_path, swift_constant)


@pytest.mark.parametrize("domain", sorted(MODULE.FIXTURE_DOMAIN_IDS))
def test_validate_rejects_unknown_fixture_domain_id(tmp_path: Path, domain: str):
    data = _marketing_demo()
    data[domain]["ghostFixture"] = next(iter(data[domain].values()))
    path = tmp_path / f"unknown_{domain}_fixture.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=rf"{domain} fixture ids .*ghostFixture"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_card_null_date_added(tmp_path: Path):
    # Swift TodayReviewCardSeed.dateAdded 是非 optional Date：null 會在 app 內
    # preconditionFailure，validator 必須在這裡就 fail-fast（IMP-0018）。
    data = _marketing_demo()
    data["todayReview"]["front"]["currentCard"]["dateAdded"] = None
    path = tmp_path / "null_today_review_date_added.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview\.front\.currentCard\.dateAdded"):
        validate_fixture_dataset_file(path)


@pytest.mark.parametrize("domain", ["vocabulary", "reviewDeck"])
def test_validate_rejects_graph_link_to_missing_in_seed_target(tmp_path: Path, domain: str):
    # KnowledgeGraphViewScenarios.swift:199 驗 graph link cardId 必 resolve 同
    # seed entries（Set(entries.kgCardId)）：dangling link 到 app 內才 fatal，
    # validator 必須在這裡 fail-fast。
    data = _marketing_demo()
    mutated = False
    for fixture_id, seed in data[domain].items():
        entries = seed.get("entries", [])
        if not entries:
            continue
        entries[0]["graphLinksByKind"]["shares_usage"] = [{
            "id": "ghost-link", "cardId": "ghost-card-id", "word": "ghostword",
            "kind": "shares_usage", "label": "相關", "confidence": 0.5,
            "reason": "dangling", "hidden": False,
        }]
        mutated = True
        break
    assert mutated, f"baseline {domain} must contain at least one entry to mutate"
    path = tmp_path / f"dangling_{domain}_graph_link.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"graphLinksByKind.*(resolve|missing|in-seed)|in-seed"):
        validate_fixture_dataset_file(path)


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


def test_validate_rejects_duplicate_asset_install_path(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["images"]["notebook_cover_app_icon"]["installAs"] = data["assets"]["books"]["catalog_reader_epub"]["installAs"]
    path = tmp_path / "duplicate_asset_install_path.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assets\.images\.notebook_cover_app_icon\.installAs duplicates assets\.books\.catalog_reader_epub\.installAs"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_asset_content_type_for_wrong_bucket(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["images"]["notebook_cover_app_icon"]["contentType"] = "application/pdf"
    path = tmp_path / "wrong_bucket_content_type.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assets\.images\.notebook_cover_app_icon\.contentType application/pdf is invalid for assets\.images"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_asset_content_type_extension_mismatch(tmp_path: Path):
    data = _marketing_demo()
    data["assets"]["books"]["catalog_reader_epub"]["contentType"] = "application/pdf"
    path = tmp_path / "asset_content_type_extension_mismatch.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"assets\.books\.catalog_reader_epub\.contentType must match \.epub as application/epub\+zip"):
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


def test_validate_rejects_unknown_user_defaults_preference_key(tmp_path: Path):
    data = _marketing_demo()
    data["preferences"]["userDefaults"]["translation_source_lagn"] = "en"
    path = tmp_path / "unknown_user_defaults_preference_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"preferences.userDefaults contains unknown app preference keys .*translation_source_lagn"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_local_only_preference_in_icloud_kvs(tmp_path: Path):
    data = _marketing_demo()
    data["preferences"]["ubiquitousKeyValueStore"]["auto_sync_enabled"] = True
    path = tmp_path / "local_only_preference_in_icloud_kvs.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"preferences.ubiquitousKeyValueStore contains unknown app preference keys .*auto_sync_enabled"):
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


def test_validate_rejects_settings_seed_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["settings"]["logged_out"]["bookSync"]
    path = tmp_path / "settings_missing_nullable_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.logged_out keys .*bookSync"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_seed_unknown_nested_key(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["preferences"]["legacyTheme"] = "sepia"
    path = tmp_path / "settings_unknown_nested_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.subscription_free.preferences keys .*legacyTheme"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_review_invalid_mode(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["reviewSettings"]["mode"] = "turbo"
    path = tmp_path / "settings_bad_review_mode.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.subscription_free.reviewSettings.mode is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_review_interval_drift(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["reviewSettings"]["customMinimumIntervalHours"] = 48
    data["settings"]["subscription_free"]["reviewSettings"]["customMaximumIntervalHours"] = 24
    path = tmp_path / "settings_bad_review_interval.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"customMaximumIntervalHours must be >= customMinimumIntervalHours"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_local_server_without_observation(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["debug_backend_local"]["kg"]["observation"] = None
    path = tmp_path / "settings_local_server_without_observation.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.debug_backend_local.kg.observation is required"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_subscription_invalid_badge_tone(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["subscription"]["badgeTone"] = "danger"
    path = tmp_path / "settings_bad_badge_tone.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.subscription_free.subscription.badgeTone is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_settings_book_sync_invalid_tone(tmp_path: Path):
    data = _marketing_demo()
    data["settings"]["subscription_free"]["bookSync"]["tone"] = "idle"
    path = tmp_path / "settings_bad_book_sync_tone.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"settings.subscription_free.bookSync.tone is invalid"):
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


def test_validate_rejects_entitlements_seed_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["entitlements"]["pro"]["pro"]["price_display"]
    path = tmp_path / "missing_nullable_entitlement_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.pro.pro keys .*price_display"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_entitlements_seed_unknown_key(tmp_path: Path):
    data = _marketing_demo()
    data["entitlements"]["pro"]["pro"]["is_admin_granted"] = False
    path = tmp_path / "unknown_entitlement_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.pro.pro keys .*is_admin_granted"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_entitlements_active_status_drift(tmp_path: Path):
    data = _marketing_demo()
    data["entitlements"]["free"]["pro"]["is_active"] = True
    path = tmp_path / "entitlement_active_status_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.free.pro.is_active must match entitlement-bearing status"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_admin_entitlement_with_app_store_product(tmp_path: Path):
    data = _marketing_demo()
    data["entitlements"]["adminGranted"]["pro"]["product_id"] = "com.wordnexus.pro.monthly"
    path = tmp_path / "admin_entitlement_with_app_store_product.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.adminGranted.pro admin source must not carry App Store product"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_entitlements_invalid_sync_timestamp(tmp_path: Path):
    data = _marketing_demo()
    data["entitlements"]["pro"]["pro"]["last_synced_at"] = "yesterday"
    path = tmp_path / "entitlement_bad_timestamp.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"entitlements.pro.pro.last_synced_at must be ISO8601"):
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


def test_validate_rejects_podcast_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["podcast"]["shelf_continue"]["episodes"][2]["lastPlayedTime"]
    path = tmp_path / "podcast_missing_nullable_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.episodes\[2\] keys .*lastPlayedTime"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_unknown_series_key(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["series"]["legacyCover"] = "cover.png"
    path = tmp_path / "podcast_unknown_series_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.series keys .*legacyCover"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_invalid_color_hex(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["series"]["colorHex"] = "blue"
    path = tmp_path / "podcast_bad_color_hex.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.series.colorHex must be #RRGGBB"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_empty_hosts(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["series"]["hostNames"] = []
    path = tmp_path / "podcast_empty_hosts.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.series.hostNames must not be empty"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_duplicate_episode_numbers(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["episodes"][1]["episodeNumber"] = 1
    path = tmp_path / "podcast_duplicate_episode_numbers.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.episodes.episodeNumber must not contain duplicate values"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_progress_after_duration(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["episodes"][0]["lastPlayedTime"] = 9999
    path = tmp_path / "podcast_progress_after_duration.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.episodes\[0\].lastPlayedTime must not exceed durationSec"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_podcast_non_positive_duration(tmp_path: Path):
    data = _marketing_demo()
    data["podcast"]["shelf_continue"]["episodes"][0]["durationSec"] = 0
    path = tmp_path / "podcast_non_positive_duration.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"podcast.shelf_continue.episodes\[0\].durationSec must be positive"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_missing_nullable_key(tmp_path: Path):
    data = _marketing_demo()
    del data["todayReview"]["front"]["currentCard"]["chapterTitle"]
    path = tmp_path / "today_review_missing_nullable_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.front.currentCard keys .*chapterTitle"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_invalid_reveal_stage(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["revealStage"] = "middle"
    path = tmp_path / "today_review_bad_reveal_stage.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.front.revealStage is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_autoplay_progress_out_of_range(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["autoplayProgress"] = 1.2
    path = tmp_path / "today_review_bad_autoplay_progress.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.front.autoplayProgress must be between 0 and 1"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_paused_without_autoplay(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["isAutoPlayPaused"] = True
    path = tmp_path / "today_review_paused_without_autoplay.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.front.isAutoPlayPaused requires isAutoPlaying=true"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_link_kind_bucket_drift(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["currentCard"]["graphLinksByKind"]["shares_usage"][0]["kind"] = "antonym"
    path = tmp_path / "today_review_link_kind_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"kind must match graphLinksByKind bucket shares_usage"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_link_confidence_out_of_range(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["front"]["currentCard"]["graphLinksByKind"]["shares_usage"][0]["confidence"] = 1.5
    path = tmp_path / "today_review_link_confidence_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"confidence must be between 0 and 1"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_today_review_completed_session_with_current_card(tmp_path: Path):
    data = _marketing_demo()
    data["todayReview"]["completed"]["currentCard"] = dict(data["todayReview"]["front"]["currentCard"])
    path = tmp_path / "today_review_completed_with_current_card.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"todayReview.completed completed session must not declare currentCard"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_unknown_key(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["legacyPhase"] = "idle"
    path = tmp_path / "sync_presenter_unknown_key.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready keys .*legacyPhase"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_invalid_phase(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["phase"] = "idle"
    path = tmp_path / "sync_presenter_invalid_phase.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.phase is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_failure_kind_without_failed_phase(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["failureKind"] = "partial"
    path = tmp_path / "sync_presenter_failure_kind_without_failed_phase.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready non-null failureKind requires failed phase"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_pending_count_drift(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["pendingCount"] = 4
    path = tmp_path / "sync_presenter_pending_count_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.pendingCount must equal addCount"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_ready_pending_rows_count_drift(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["pendingRows"].pop()
    path = tmp_path / "sync_presenter_ready_rows_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.pendingRows count must equal pendingCount"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_invalid_step_state(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["running"]["steps"][0]["status"] = "queued"
    path = tmp_path / "sync_presenter_invalid_step_state.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.running.steps\[0\].upload_delete.status is invalid"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_step_progress_drift(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["running"]["steps"][0]["current"] = 2
    path = tmp_path / "sync_presenter_step_progress_drift.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.running.steps\[0\].current must not exceed total"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_invalid_pending_row_uuid(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["pendingRows"][0]["id"] = "not-a-uuid"
    path = tmp_path / "sync_presenter_invalid_row_uuid.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.pendingRows\[0\].id must be UUID"):
        validate_fixture_dataset_file(path)


def test_validate_rejects_sync_presenter_invalid_pending_row_tone(tmp_path: Path):
    data = _marketing_demo()
    data["syncPresenter"]["ready"]["pendingRows"][0]["actionTone"] = "warning"
    path = tmp_path / "sync_presenter_invalid_row_tone.json"
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(UIWorldManifestError, match=r"syncPresenter.ready.pendingRows\[0\].actionTone is invalid"):
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
