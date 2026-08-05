"""Emitter: demo SoT -> iOS UI World FixtureDatasetDocument.

FROZEN 2026-08-05 — 停止擴張，不停止運作。凍結範圍與理由見
`docs/reference/catalog_scope.md` §FROZEN。本檔邏輯完好、隨時可跑（送審 desired
bundle 仍經 `ops/app_review_evidence.py` 走這條路），但**不再隨 iOS seed 演進同步**：
復業時跑 spec 模式會噴 `spec 錨日 ... 距今 N 天（> 48h）` 的 staleness WARN——**那是預期的**，
解法就是先跑（同樣凍結的）`marketing_account/shape_history.py` 重新錨定再 emit。
不新增 domain、不加 seed 欄位、不重生 generated world。要復業先讀該節。
`--check` drift gate 與 `ops/tests/test_demo_ios_emitter.py` **刻意保留**——凍結期
它們的角色從「逼你同步」變成「守衛」：誰偷改這條凍結的投影鏈，它會紅。

Phase B implementation. Mirrors the Phase-A mapping contract below, byte-for-byte
deterministic so `--check` is a true drift gate.

OUTPUT PATH(S)
  ops/demo/generated/ios_fixture_dataset.json   (FixtureDatasetDocument JSON)

INJECTION SEAM (no Swift logic change to the loader)
  The fixture JSON is injected into the running app via the env var
  KG_FIXTURE_DATASET_DEFLATE_B64 (base64 of the raw-DEFLATE-compressed JSON
  bytes; plaintext base64 of a multi-MB world overflows the ~1MB spawn env
  block) — see ios/BooksAndVocab/Support/Fixtures/Core/FixtureDatasetStore.swift
  and ops/lib/fixture_dataset_env.sh. This emitter writes the *plaintext* JSON;
  the UITest harness compresses+base64s it into the env var via the seam:
      ./ops/ios_test.sh --ui --dataset-file ops/demo/generated/ios_fixture_dataset.json ...
  UITestAppLaunch.swift (UITestLaunchConfiguration.launchEnvironment) forwards
  that var into the app process. emit() also prints the ready-to-export deflate
  base64 when commit so it can be exported directly without the shell helper.

SCHEMA NOTE
  The Phase-A skeleton planned schema "kg.fixture_dataset.v1". The Swift SoT
  (FixtureDatasetStore.decode + RepoFixtureDatasetsContractTests) is authoritative.
  Repo UI Worlds now use "kg.fixture.dataset.v2", which adds the top-level
  asset manifest. The generated demo world is emitted from the repo UI World
  manifest baseline, then only identity-owned auth fields and datasetID are
  overlaid from demo_identity.json. This keeps Catalog, UITest, visual capture,
  and generated demo on the same fixture shape instead of maintaining a second
  partial iOS fixture skeleton.

DOCUMENT SHAPE  (FixtureDatasetDocument top-level keys — exact, see Swift struct)
  schema       <- "kg.fixture.dataset.v2"
  datasetID    <- "demo-" + identity.user_id
  assets/settings/bookshelf/todayReview/notebook/podcast/runtimePodcast/reader/
                 vocabulary/reviewDeck <- copied from ops/fixtures/ui_worlds/marketing_demo.json
  auth         <- baseline auth fixture set, with signedIn identity fields
                 overlaid from demo identity and explicit keychain/UI auth state
  entitlements <- copied from the baseline UI World so generated demo exposes
                  the same free/pro/cancelled/admin catalog states

  Keyed decoding silently ignores unknown top-level keys; emit() MUST NOT add keys
  outside FixtureDatasetDocument.knownTopLevelKeys, and the domain sub-keys must
  be declared fixture IDs known by the Swift manifest contract.

CHECK MODE
  Re-emit the UI World file in memory, byte-compare against the committed artifact,
  return a drift verdict (exit 1 on drift via build_demo.py).

SPEC MODE  (marketing-account projector, Phase 2/6)
  `build_demo.py emit-ios --spec <kg.seed_spec.v1> --out <path>` derives the
  vocabulary / notebook / reviewDeck / todayReview domains from a Phase-1
  `ops_cli world-export` seed spec (projection rules live in
  ops/demo/spec_world.py; deterministic, byte-stable). Every other domain plus
  the identity auth overlay follows the exact baseline recipe above. Inside the
  four spec domains, the account-data-independent UI-chrome fixtures listed in
  SPEC_BASELINE_KEPT_FIXTURES stay byte-equal to the baseline — notably the
  notebook.readerPicker* rows are cross-referenced by baseline bookshelf
  `preferredNotebookId` and MUST NOT be replaced. Spec mode writes ONLY to the
  caller-provided --out path; the committed generated artifact and its --check
  drift gate are frozen. --check in spec mode byte-compares --out against a
  fresh emit of --spec. datasetID = "spec-" + sha256(canonical spec)[:12].
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import sys
import tempfile
import zlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sot import DemoSoT

_HERE = Path(__file__).resolve().parent
_REPO_ROOT = _HERE.parent.parent  # ops/demo -> ops -> repo root
_OPS_DIR = _REPO_ROOT / "ops"
if str(_OPS_DIR) not in sys.path:
    sys.path.insert(0, str(_OPS_DIR))
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import spec_world  # noqa: E402
from ui_world_manifest import UIWorldManifestError, validate_fixture_dataset_file  # noqa: E402

_LOGGER = logging.getLogger(__name__)

GENERATED_DIR = _HERE / "generated"
FIXTURE_JSON_PATH = GENERATED_DIR / "ios_fixture_dataset.json"

FIXTURE_SCHEMA = "kg.fixture.dataset.v2"
BASE_UI_WORLD_PATH = _REPO_ROOT / "ops/fixtures/ui_worlds/marketing_demo.json"
FIXTURE_TOP_LEVEL_KEYS = {
    "schema",
    "datasetID",
    "assets",
    "preferences",
    "auth",
    "entitlements",
    "settings",
    "bookshelf",
    "todayReview",
    "notebook",
    "podcast",
    "runtimePodcast",
    "reader",
    "vocabulary",
    "reviewDeck",
    "syncPresenter",
    # marketing-capture-only scene inputs（QA scene 一律忽略整個 domain）：
    # reviewClock（錨日凍結時鐘，plan 驅動）+ readerPassage（reader 行銷段落）+
    # wordDetail（Word Detail 行銷 seed），皆 spec/plan 驅動。Swift
    # FixtureDatasetStore.CodingKeys 需 Phase 2 加 `case marketingCapture` 才不會在
    # decode 撞 unknown-top-level-key（見本檔 module docstring）。
    "marketingCapture",
}
MARKETING_CAPTURE_KEYS = frozenset({"reviewClock", "readerPassage", "wordDetail"})
REVIEW_CLOCK_FIELD_KEYS = frozenset(
    {"frozenNow", "frozenEpoch", "anchorDay", "source"})
IDENTITY_OWNED_SIGNED_IN_KEYS = {
    "isLoggedIn",
    "userId",
    "token",
    "displayName",
    "email",
    "provider",
    "providerUserId",
    "keychainTokenState",
    "authError",
    "isAuthenticating",
}
# Review-clock freeze overlay：行銷帳號的世界要確定式凍結在 anchor，注入後 review
# 排程的「now」= progressPausedAt（iOS ReviewSettings.swift:131-132），不隨牆鐘漂移。
# 這 3 個 ReviewSettings.Keys 是唯一允許偏離 baseline preferences 的 key，且對
# userDefaults / ubiquitousKeyValueStore 兩 store 都套（LWW updated_at 對齊 paused_at）。
REVIEW_CLOCK_OVERLAY_KEYS = frozenset({
    "review_settings_progress_paused",
    "review_settings_progress_paused_at",
    "review_settings_progress_updated_at",
})
REVIEW_CLOCK_OVERLAY_STORES = ("userDefaults", "ubiquitousKeyValueStore")
SPEC_DOMAINS = frozenset({"vocabulary", "notebook", "reviewDeck", "todayReview"})
# spec 模式下四 domain 內仍沿用 baseline 的 fixture id。兩類：
# (a) 帳號資料無關的 UI-chrome / gallery 語意；其中 notebook.readerPicker* 的
#     rows 是 baseline bookshelf `preferredNotebookId` 的跨 domain ref 解析目標，
#     替換會破壞 cross-ref 驗證。
# (b) content-pinned：catalog scenario（含 UITest seed seam）釘死特定 word /
#     query 命中數 / exact count / archived 量 / probeword 合成 deck，任意合法
#     spec 無法保證 → 投影必致 preconditionFailure / XCTFail。逐條 SoT 見行內
#     註解（盤點 2026-07-08，涵蓋 vocabulary/notebook/reviewDeck/todayReview
#     全部 consumer——catalog scenarios + UITestFixtureSeed+* seam；reviewDeck
#     phase* 與 todayReview 各 session、notebook empty/single/populated 無
#     content pin，維持投影）。
SPEC_BASELINE_KEPT_FIXTURES = (
    # (a) UI-chrome / gallery
    ("notebook", "coverGallery"),
    ("notebook", "cardGallery"),
    ("notebook", "editGallery"),
    ("notebook", "readerPickerMany"),
    ("notebook", "readerPickerPopulated"),
    ("todayReview", "longContent"),
    # (b) content-pinned vocabulary fixtures
    # WordDetailScenarios.swift: "ephemeral"(rich)/"terse"(minimal) 各恰 1 命中
    ("vocabulary", "wordDetail"),
    # WordEditScenarios.swift: serendipity / ephemeral / verisimilitude /
    # antidisestablishmentarianism 四字必在
    ("vocabulary", "wordEdit"),
    # KGVocabSearchScenarios.swift: "影響">1、"ambiguous"==1、"zzzznotaword"==0
    # 命中（UITestFixtureSeed+Search.swift 吃同一 seed）
    ("vocabulary", "searchVocabNotebook"),
    # KGVocabRowScenarios.swift: entries.count == KGVocabRowFixture.allCases.count
    # 且 index-addressed（每列對應固定 row state）
    ("vocabulary", "kgVocabRow"),
    # VocabScenarios.swift(VocabManifestEntries): 恰 6 entries、index-addressed
    ("vocabulary", "vocabLinkedCards"),
    # ArchivedVocabScenarios.swift: populated ≥5 / single ==1 / long ≥40 條
    # archived——spec 可合法 0 archived（行銷帳號實測 0）
    ("vocabulary", "archivedPopulated"),
    ("vocabulary", "archivedSingle"),
    ("vocabulary", "archivedLong"),
    # (b) content-pinned reviewDeck fixtures（UITest 量測 deck）
    # NotebookReviewFlowUITests.swift:85,125,162: frontWord 必須 hasPrefix
    # "probeword"、背面譯文必須配對「量測卡片 N 的譯文」——合成量測資料，
    # 非帳號資料；probe 另為 flip-probe rig 卡組（UITestFixtureSeed+TodayReview）
    ("reviewDeck", "probe"),
    ("reviewDeck", "notebookReviewDeck"),
)


def _overlay_identity_auth(baseline_auth: dict[str, Any], identity: dict[str, Any]) -> dict[str, Any]:
    auth = dict(baseline_auth)
    signed_in = dict(auth["signedIn"])
    signed_in.update(
        {
            "isLoggedIn": True,
            "userId": identity["user_id"],
            "token": identity["access_token"],
            "displayName": identity["display_name"],
            "email": identity["email"],
            "provider": identity["provider"],
            "providerUserId": identity["provider_user_id"],
            "keychainTokenState": "available",
            "authError": None,
            "isAuthenticating": False,
        }
    )
    auth["signedIn"] = signed_in
    return auth


def _overlay_review_clock(
    baseline_preferences: dict[str, Any], frozen_at: "object"
) -> dict[str, Any]:
    """Overlay：把 review 時鐘凍結在 frozen_at（datetime）。兩 store 都 paused@epoch。

    仿 `_overlay_identity_auth` 的定點 overlay 模式——只動 REVIEW_CLOCK_OVERLAY_KEYS，
    其餘 preferences 原封不動。baseline 缺 review_settings_progress_paused_at → 新增。
    """
    epoch = int(frozen_at.timestamp())  # type: ignore[attr-defined]
    preferences = dict(baseline_preferences)
    for store in REVIEW_CLOCK_OVERLAY_STORES:
        merged = dict(preferences[store])
        merged["review_settings_progress_paused"] = True
        merged["review_settings_progress_paused_at"] = epoch
        merged["review_settings_progress_updated_at"] = epoch
        preferences[store] = merged
    return preferences


def _review_clock_field(frozen_at: "object") -> dict[str, Any]:
    """把凍結時刻（datetime）攤成 reviewClock 顯式欄位。

    frozenNow / frozenEpoch = 同一凍結時刻（= preferences review-clock overlay 的
    epoch，單一 SoT）；anchorDay = 該時刻的 UTC 日（恆等於 plan.anchor_day，
    因 freeze = anchor 00:00Z + (24-max_offset)h - 1s，落在 anchor 當日 UTC）。
    """
    from datetime import timezone

    dt = frozen_at.astimezone(timezone.utc)  # type: ignore[attr-defined]
    return {
        "frozenNow": dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "frozenEpoch": int(dt.timestamp()),
        "anchorDay": dt.date().isoformat(),
        "source": "history_plan.anchor_day",
    }


def _build_marketing_capture(
    spec: dict[str, Any], *, review_clock_frozen_at: "object | None"
) -> dict[str, Any]:
    """marketingCapture domain：reviewClock（plan 凍結時鐘，未凍結時 null）
    + readerPassage（reader 行銷段落）+ wordDetail（Word Detail 行銷 seed），
    後二者 spec 驅動、恆存在於 spec 模式。"""
    return {
        "reviewClock": (
            _review_clock_field(review_clock_frozen_at)
            if review_clock_frozen_at is not None else None
        ),
        "readerPassage": spec_world.derive_reader_passage(spec),
        "wordDetail": spec_world.derive_word_detail(spec),
    }


def _build_fixture_document(sot: DemoSoT) -> dict[str, Any]:
    identity = sot.identity
    baseline = _load_base_ui_world()
    document = dict(baseline)
    document["schema"] = FIXTURE_SCHEMA
    document["datasetID"] = f"demo-{identity['user_id']}"
    document["auth"] = _overlay_identity_auth(baseline["auth"], identity)
    _validate_fixture_document(document, baseline)
    return document


def _spec_digest(spec: dict[str, Any]) -> str:
    canonical = json.dumps(spec, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()[:12]


def _build_spec_fixture_document(
    sot: DemoSoT, spec: dict[str, Any], *, review_clock_frozen_at: "object | None" = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """spec 模式:baseline + 四 domain spec-derived merge + identity auth overlay。

    review_clock_frozen_at（datetime）非 None 時,額外對 preferences 套 review-clock
    freeze overlay（凍結在 anchor 末刻）;None = 不凍,維持既有 byte-equal baseline 行為。
    """
    baseline = _load_base_ui_world()
    derived, stats = spec_world.derive_domains(spec)
    document = dict(baseline)
    document["schema"] = FIXTURE_SCHEMA
    document["datasetID"] = f"spec-{_spec_digest(spec)}"
    for domain, seeds in derived.items():
        merged = dict(baseline[domain])
        merged.update(seeds)
        document[domain] = merged
    document["auth"] = _overlay_identity_auth(baseline["auth"], sot.identity)
    document["marketingCapture"] = _build_marketing_capture(
        spec, review_clock_frozen_at=review_clock_frozen_at)
    if review_clock_frozen_at is not None:
        document["preferences"] = _overlay_review_clock(baseline["preferences"], review_clock_frozen_at)
    _validate_fixture_document(
        document, baseline, spec_domains=SPEC_DOMAINS,
        review_clock_frozen=review_clock_frozen_at is not None,
    )
    return document, stats


def _load_base_ui_world() -> dict[str, Any]:
    data = json.loads(BASE_UI_WORLD_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{BASE_UI_WORLD_PATH} top-level must be a JSON object")
    if data.get("schema") != FIXTURE_SCHEMA:
        raise ValueError(
            f"{BASE_UI_WORLD_PATH} schema must be {FIXTURE_SCHEMA!r}, got {data.get('schema')!r}"
        )
    return data


def _validate_review_clock_overlay(
    preferences: dict[str, Any], baseline_preferences: dict[str, Any]
) -> None:
    """review-clock freeze 模式:preferences 只允許在 REVIEW_CLOCK_OVERLAY_KEYS 偏離。

    store set 不可變、不可刪 key;新增/改值的 key 必須全落在時鐘 overlay 白名單。
    精準守住「只有時鐘 key 可變」,不整域放行。
    """
    if set(preferences) != set(baseline_preferences):
        raise ValueError(
            "review-clock freeze must not change preferences store set "
            f"(got {sorted(preferences)}, baseline {sorted(baseline_preferences)})"
        )
    for store, base_store in baseline_preferences.items():
        doc_store = preferences[store]
        added = set(doc_store) - set(base_store)
        removed = set(base_store) - set(doc_store)
        if removed:
            raise ValueError(
                f"review-clock freeze must not remove preferences.{store} keys {sorted(removed)}"
            )
        if added - REVIEW_CLOCK_OVERLAY_KEYS:
            raise ValueError(
                f"review-clock freeze added non-clock preferences.{store} keys "
                f"{sorted(added - REVIEW_CLOCK_OVERLAY_KEYS)}"
            )
        changed = {k for k in set(doc_store) & set(base_store) if doc_store[k] != base_store[k]}
        disallowed = sorted(changed - REVIEW_CLOCK_OVERLAY_KEYS)
        if disallowed:
            raise ValueError(
                f"review-clock freeze changed non-clock preferences.{store} keys {disallowed}"
            )


def _validate_marketing_capture_field(
    document: dict[str, Any], *, review_clock_frozen: bool
) -> None:
    """marketingCapture 結構把關（emit_ios 面；深度形狀驗證在 ui_world_manifest）。

    keys 恆 == {reviewClock, readerPassage}；readerPassage keys 恆 == READER_PASSAGE_KEYS；
    reviewClock 在凍結 emit 下必為完整 clock dict，否則允許 None（未凍結 spec 模式）
    或 baseline 沿用的完整 clock dict（baseline 模式攜帶行銷世界的 clock）。
    """
    mc = document.get("marketingCapture")
    if not isinstance(mc, dict) or set(mc) != MARKETING_CAPTURE_KEYS:
        got = sorted(mc) if isinstance(mc, dict) else type(mc).__name__
        raise ValueError(
            f"marketingCapture keys must be {sorted(MARKETING_CAPTURE_KEYS)}, got {got}")
    passage = mc["readerPassage"]
    if not isinstance(passage, dict) or set(passage) != set(spec_world.READER_PASSAGE_KEYS):
        got = sorted(passage) if isinstance(passage, dict) else type(passage).__name__
        raise ValueError(
            f"marketingCapture.readerPassage keys must be {sorted(spec_world.READER_PASSAGE_KEYS)}, "
            f"got {got}")
    word_detail = mc["wordDetail"]
    if not isinstance(word_detail, dict) or not word_detail.get("entries"):
        raise ValueError("marketingCapture.wordDetail must be a vocab seed with non-empty entries")
    clock = mc["reviewClock"]
    if review_clock_frozen:
        if not isinstance(clock, dict) or set(clock) != set(REVIEW_CLOCK_FIELD_KEYS):
            raise ValueError(
                "frozen emit requires marketingCapture.reviewClock with keys "
                f"{sorted(REVIEW_CLOCK_FIELD_KEYS)}")
    elif clock is not None and (not isinstance(clock, dict)
                               or set(clock) != set(REVIEW_CLOCK_FIELD_KEYS)):
        raise ValueError(
            "marketingCapture.reviewClock must be null or a full clock dict with keys "
            f"{sorted(REVIEW_CLOCK_FIELD_KEYS)}")


def _validate_fixture_document(
    document: dict[str, Any],
    baseline: dict[str, Any],
    *,
    spec_domains: frozenset[str] = frozenset(),
    review_clock_frozen: bool = False,
) -> None:
    """Fail loud if generated demo stops being a UI World + identity overlay.

    `spec_domains`（spec 模式）內的 domain 允許內容偏離 baseline，但 fixture id
    key set 必須與 baseline 完全一致（Swift *FixtureID.allCases registry 契約），
    且 SPEC_BASELINE_KEPT_FIXTURES 列出的 UI-chrome fixture 必須 byte-equal。
    `review_clock_frozen` 時 preferences 改由 _validate_review_clock_overlay 精準把關
    （只允許時鐘 key 偏離），其餘 domain 仍須 byte-equal baseline。
    """
    top_level = set(document)
    if top_level != FIXTURE_TOP_LEVEL_KEYS:
        extra = sorted(top_level - FIXTURE_TOP_LEVEL_KEYS)
        missing = sorted(FIXTURE_TOP_LEVEL_KEYS - top_level)
        raise ValueError(
            "generated iOS UI World has invalid top-level keys "
            f"extra={extra} missing={missing}"
        )

    baseline_top_level = set(baseline)
    if baseline_top_level != FIXTURE_TOP_LEVEL_KEYS:
        extra = sorted(baseline_top_level - FIXTURE_TOP_LEVEL_KEYS)
        missing = sorted(FIXTURE_TOP_LEVEL_KEYS - baseline_top_level)
        raise ValueError(
            f"{BASE_UI_WORLD_PATH} has invalid top-level keys extra={extra} missing={missing}"
        )

    # marketingCapture 恆為 spec/plan 驅動（reviewClock 隨 plan、readerPassage 隨
    # spec），永不對 baseline byte-equal；改由 _validate_marketing_capture_field 驗形狀。
    frozen_exclude = {"preferences"} if review_clock_frozen else set()
    for key in sorted(FIXTURE_TOP_LEVEL_KEYS - {"datasetID", "auth", "marketingCapture"}
                      - spec_domains - frozen_exclude):
        if document[key] != baseline[key]:
            raise ValueError(
                "generated iOS UI World may only overlay identity-owned auth; "
                f"domain {key!r} drifted from {BASE_UI_WORLD_PATH}"
            )
    _validate_marketing_capture_field(document, review_clock_frozen=review_clock_frozen)
    if review_clock_frozen:
        _validate_review_clock_overlay(document["preferences"], baseline["preferences"])

    for domain in sorted(spec_domains):
        if set(document[domain]) != set(baseline[domain]):
            extra = sorted(set(document[domain]) - set(baseline[domain]))
            missing = sorted(set(baseline[domain]) - set(document[domain]))
            raise ValueError(
                f"spec-derived domain {domain!r} fixture id key set must equal baseline "
                f"(Swift allCases registry contract) extra={extra} missing={missing}"
            )
    for domain, fixture_id in SPEC_BASELINE_KEPT_FIXTURES:
        if domain in spec_domains and document[domain][fixture_id] != baseline[domain][fixture_id]:
            raise ValueError(
                f"spec mode must keep UI-chrome fixture {domain}.{fixture_id} byte-equal to baseline"
            )

    auth = document["auth"]
    baseline_auth = baseline["auth"]
    if set(auth) != set(baseline_auth):
        raise ValueError("generated iOS UI World auth fixture keys must match baseline")

    for fixture_key, seed in auth.items():
        if fixture_key != "signedIn":
            if seed != baseline_auth[fixture_key]:
                raise ValueError(
                    "generated iOS UI World may only overlay auth.signedIn; "
                    f"auth.{fixture_key} drifted from baseline"
                )
            continue

        signed_in_keys = set(seed)
        baseline_signed_in_keys = set(baseline_auth[fixture_key])
        if signed_in_keys != baseline_signed_in_keys:
            raise ValueError("generated iOS UI World auth.signedIn keys must match baseline")

        changed = {
            key
            for key in signed_in_keys
            if seed[key] != baseline_auth[fixture_key][key]
        }
        disallowed = sorted(changed - IDENTITY_OWNED_SIGNED_IN_KEYS)
        if disallowed:
            raise ValueError(
                "generated iOS UI World auth.signedIn changed non-identity keys "
                f"{disallowed}"
            )


def _json_bytes(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON: 2-space indent, UTF-8, no key reordering, trailing NL."""
    return (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _validate_fixture_json_bytes(content: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="kg-demo-ui-world-") as tmp:
        path = Path(tmp) / "ios_fixture_dataset.json"
        path.write_bytes(content)
        try:
            validate_fixture_dataset_file(path, label="Generated demo UI World")
        except UIWorldManifestError as exc:
            raise ValueError(str(exc)) from exc


def _artifacts(sot: DemoSoT) -> list[tuple[Path, bytes]]:
    document = _build_fixture_document(sot)
    content = _json_bytes(document)
    _validate_fixture_json_bytes(content)
    return [(FIXTURE_JSON_PATH, content)]


def _spec_build(
    sot: DemoSoT, *, spec_path: Path, out_path: Path,
    review_clock_frozen_at: "object | None" = None,
) -> tuple[Path, bytes, dict[str, Any], dict[str, Any], dict[str, Any]]:
    """spec 模式共用管線:載入 → 投影 → serialize → shared-validator 驗證。

    `_spec_artifacts`(測試 seam)與 `_emit_spec`(CLI)都走這一條,防兩路徑 drift。
    """
    spec = spec_world.load_seed_spec(Path(spec_path))
    document, stats = _build_spec_fixture_document(
        sot, spec, review_clock_frozen_at=review_clock_frozen_at)
    content = _json_bytes(document)
    _validate_fixture_json_bytes(content)
    return Path(out_path), content, document, stats, spec


def _spec_artifacts(
    sot: DemoSoT, *, spec_path: Path, out_path: Path,
    review_clock_frozen_at: "object | None" = None,
) -> list[tuple[Path, bytes]]:
    """spec 模式 artifact:回傳 (out_path, bytes)。"""
    out, content, _document, _stats, _spec = _spec_build(
        sot, spec_path=spec_path, out_path=out_path,
        review_clock_frozen_at=review_clock_frozen_at)
    return [(out, content)]


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(_REPO_ROOT))
    except ValueError:
        _LOGGER.debug("Cannot compute relative path from repo root for %s", path)
        return str(path)


_SPEC_STALENESS_HOURS = 48.0


def spec_staleness_warning(spec: dict[str, Any], *, now: "object | None" = None) -> str | None:
    """spec 錨日防呆：iOS streak / 學習日曆的「今天」是 render 時的牆鐘，spec 的
    複習事件卻是絕對日期 —— 拿陳舊 spec 出圖時 streak 歸零、日曆變空。以
    max(last_reviewed_at) 當 spec 錨日，距 now 超過 _SPEC_STALENESS_HOURS 即回傳
    WARN 訊息（純提示，不影響輸出 bytes；重新錨定走
    ops/demo/marketing_account/shape_history.py）。"""
    from datetime import datetime, timezone

    latest: "datetime | None" = None
    for card in spec.get("cards", []):
        raw = (card.get("review") or {}).get("last_reviewed_at")
        if not raw:
            continue
        s = str(raw).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(s)
        except ValueError:
            continue  # 格式錯誤由 load_seed_spec/投影面把關，防呆不重複驗
        dt = dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        if latest is None or dt > latest:
            latest = dt
    if latest is None:
        return None
    now_dt = now if now is not None else datetime.now(timezone.utc)
    age_hours = (now_dt - latest).total_seconds() / 3600
    if age_hours <= _SPEC_STALENESS_HOURS:
        return None
    return (
        f"WARN: spec 錨日 {latest.isoformat()} 距今 {age_hours / 24:.1f} 天（> 48h）；"
        "以此 spec 出圖時 streak / 學習日曆會因牆鐘漂移而崩。先用 "
        "ops/demo/marketing_account/shape_history.py 重新錨定再 emit。"
    )


def _emit_spec(
    sot: DemoSoT,
    *,
    spec_path: Path,
    out_path: Path,
    check: bool,
    commit: bool,
    review_clock_frozen_at: "object | None" = None,
) -> dict:
    """Spec 模式的 emit:輸出到呼叫者指定路徑，不碰 committed artifact。"""
    out, content, document, stats, spec = _spec_build(
        sot, spec_path=spec_path, out_path=out_path,
        review_clock_frozen_at=review_clock_frozen_at)
    staleness = spec_staleness_warning(spec)
    if staleness:
        print(staleness, file=sys.stderr)

    base: dict[str, Any] = {
        "mode": "spec",
        "spec": str(spec_path),
        "datasetID": document["datasetID"],
        "specStats": stats,
        "bytes": len(content),
        "base64Bytes": (len(content) + 2) // 3 * 4,  # KG_FIXTURE_DATASET_B64 注入體積
        "specDerivedDomains": sorted(SPEC_DOMAINS),
        "baselineKeptFixtures": [f"{d}.{f}" for d, f in SPEC_BASELINE_KEPT_FIXTURES],
    }
    if staleness:
        base["stalenessWarning"] = staleness

    if check:
        if not out.exists():
            return {**base, "action": "check", "drift": True,
                    "drifted": [{"path": str(out), "reason": "missing"}]}
        actual = out.read_bytes()
        drifted = (
            [{"path": str(out), "reason": "content-mismatch",
              "committed_bytes": len(actual), "fresh_bytes": len(content)}]
            if actual != content else []
        )
        return {**base, "action": "check", "drift": bool(drifted), "drifted": drifted}

    if commit:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(content)
        return {
            **base,
            "action": "commit",
            "drift": False,
            "written": [str(out)],
            "inject_hint": (
                f"./ops/ios_ops.sh catalog snapshots --dataset-file {out} ...  # or: "
                f"./ops/ios_test.sh --ui --dataset-file {out} ..."
            ),
        }

    return {**base, "action": "dry-run", "drift": False, "planned_paths": [str(out)]}


def emit(
    sot: DemoSoT,
    *,
    check: bool = False,
    commit: bool = False,
    spec_path: str | Path | None = None,
    out_path: str | Path | None = None,
    review_clock_frozen_at: "object | None" = None,
) -> dict:
    """Emit the iOS UI World FixtureDatasetDocument JSON from the SoT.

    Args:
        sot: validated DemoSoT bundle (identity + dataset).
        check: re-emit in memory and byte-compare against the committed
            artifact(s) (baseline mode) or against --out (spec mode); return a
            drift report instead of writing.
        commit: write the generated file(s) to disk (and print the deflate
            base64 the harness exports as KG_FIXTURE_DATASET_DEFLATE_B64).
            When False (and check
            False), dry-run returning the planned output paths.
        spec_path: kg.seed_spec.v1 input — switches to SPEC MODE (see module
            docstring). Must be given together with out_path.
        out_path: spec-mode output path (never the committed generated artifact).
        review_clock_frozen_at: datetime (spec mode only) — freeze the review
            clock at this instant via a preferences overlay. None = no freeze
            (backward-compatible; preferences stay byte-equal to baseline).

    Returns:
        A dict describing the action (paths written / drift verdict / deflate base64).
    """
    if (spec_path is None) != (out_path is None):
        raise ValueError(
            "spec mode requires BOTH --spec <kg.seed_spec.v1> and --out <path> "
            "(got only one of them)"
        )
    if review_clock_frozen_at is not None and spec_path is None:
        raise ValueError("review_clock_frozen_at is only supported in spec mode (needs --spec/--out)")
    if spec_path is not None:
        assert out_path is not None
        return _emit_spec(
            sot, spec_path=Path(spec_path), out_path=Path(out_path),
            check=check, commit=commit, review_clock_frozen_at=review_clock_frozen_at,
        )

    artifacts = _artifacts(sot)

    if check:
        drifted: list[dict[str, Any]] = []
        missing: list[str] = []
        for path, expected in artifacts:
            if not path.exists():
                missing.append(_rel(path))
                drifted.append({"path": _rel(path), "reason": "missing"})
                continue
            actual = path.read_bytes()
            if actual != expected:
                drifted.append(
                    {
                        "path": _rel(path),
                        "reason": "content-mismatch",
                        "committed_bytes": len(actual),
                        "fresh_bytes": len(expected),
                    }
                )
        return {
            "action": "check",
            "drift": bool(drifted),
            "drifted": drifted,
            "missing": missing,
            "checked": [_rel(p) for p, _ in artifacts],
        }

    if commit:
        written: list[str] = []
        for path, content in artifacts:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            written.append(_rel(path))
        # raw DEFLATE (wbits=-15) == Apple NSData .zlib; plaintext base64 of a
        # multi-MB world overflows the ~1MB spawn env block.
        compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
        fixture_deflate_b64 = base64.b64encode(
            compressor.compress(artifacts[0][1]) + compressor.flush()
        ).decode("ascii")
        return {
            "action": "commit",
            "drift": False,
            "written": written,
            "datasetID": json.loads(artifacts[0][1])["datasetID"],
            "fixture_dataset_deflate_b64": fixture_deflate_b64,
            "inject_hint": (
                "export KG_FIXTURE_DATASET_DEFLATE_B64=<fixture_dataset_deflate_b64>  # or: "
                "./ops/ios_test.sh --ui --dataset-file "
                f"{_rel(FIXTURE_JSON_PATH)} ..."
            ),
        }

    # dry-run
    return {
        "action": "dry-run",
        "drift": False,
        "planned_paths": [_rel(p) for p, _ in artifacts],
        "datasetID": json.loads(artifacts[0][1])["datasetID"],
    }
