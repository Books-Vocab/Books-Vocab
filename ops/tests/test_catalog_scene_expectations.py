"""Catalog scene 的數量門檻必須是凍結 UI World 供得起的。

背景：`docs/reference/catalog_scope.md` §FROZEN 之後 `ops/fixtures/ui_worlds/
marketing_demo.json` 不再擴張，但兩個 catalog scene 仍宣告著行銷密度時代的門檻
（`visibleAtLeast(80)` / `(80,50,80,50)`），於是 `ios_ops.sh catalog snapshots`
每趟都在 scene 建構期 `preconditionFailure` 死掉（exitCode=65，backlog IMP-0064）。
Swift 端的 precondition 只有在**跑得動模擬器**時才會講話；這支測試把同一個矛盾
搬到純 Python、可在 Linux CI 上跑的地方。

**斷言的是「宣告的下限沒有結構性不可能」，不是「執行期實際會拿到幾個」**：

- `visibleEntries` / `graphLinks` 直接由 world 的資料欄位決定（`syncStatus` /
  `actionType` / `isArchived` / `graphLinksByKind[].isHidden`），這幾行是資料性質
  的鏡像，鏡得起。
- `graphNodes` / `graphEdges` 另外經過 `KnowledgeGraphPresentation`（degree 過濾、
  tier 規則）。**刻意不鏡像那段呈現邏輯**——會漂的鏡子比擋不住的上界更糟。這裡只
  用它們的無條件上界（node 至多一個可見且有 kgCardId 的 entry、edge 至多一條 link），
  執行期的真值仍由 Swift 自己的 precondition 負責。

換句話說：本測試抓的是「world 只有 4 筆卻宣告 80」這一類；抓不到「宣告 4 但呈現層
只吐 3」。後者歸 Swift。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORLD_PATH = ROOT / "ops" / "fixtures" / "ui_worlds" / "marketing_demo.json"
VOCAB_LIST_SCENE = ROOT / "ios" / "BooksAndVocab" / "Debug" / "Scenarios" / "VocabularyListViewScenarios.swift"
GRAPH_SCENE = ROOT / "ios" / "BooksAndVocab" / "Debug" / "Scenarios" / "KnowledgeGraphViewScenarios.swift"
CATALOG_SCENE = ROOT / "ios" / "BooksAndVocab" / "Debug" / "CatalogScene.swift"
SCENARIOS_DIR = ROOT / "ios" / "BooksAndVocab" / "Debug" / "Scenarios"

FROZEN_SCREEN_ID_COUNT = 20
FROZEN_DEBUG_SCENARIO_FILES = frozenset(
    {
        "AppStartupRecoveryScenarios.swift",
        "ArchivedVocabScenarios.swift",
        "BannerScenarios.swift",
        "BookCardScenarios.swift",
        "BookshelfViewScenarios.swift",
        "CollocationExplainScenarios.swift",
        "DeleteAccountSheetScenarios.swift",
        "ExploreViewScenarios.swift",
        "KGVocabEmptyStateScenarios.swift",
        "KGVocabRowScenarios.swift",
        "KGVocabSearchScenarios.swift",
        "KnowledgeGraphViewScenarios.swift",
        "LinkReasonSheetScenarios.swift",
        "LoginSheetScenarios.swift",
        "MarketingReviewClock.swift",
        "NotebookCardEditorialCoverScenarios.swift",
        "NotebookCoverScenarios.swift",
        "NotebookEditSheetScenarios.swift",
        "NotebookFilterChipScenarios.swift",
        "NotebookListScenarios.swift",
        "NotebookListViewScenarios.swift",
        "NotebookReviewActionBarScenarios.swift",
        "NotebooksScenarios.swift",
        "PDFReaderViewScenarios.swift",
        "PaywallScenarios.swift",
        "PodcastContinueCardScenarios.swift",
        "PodcastEpisodeListViewScenarios.swift",
        "PodcastHomeViewScenarios.swift",
        "PodcastPlayerScenarios.swift",
        "PodcastPlayerViewScenarios.swift",
        "PodcastSentenceCellsScenarios.swift",
        "PodcastSeriesHeroScenarios.swift",
        "PodcastSettingsPopoverScenarios.swift",
        "PodcastShelfCardsScenarios.swift",
        "PodcastShelfScenarios.swift",
        "ReaderChromeScenarios.swift",
        "ReaderNotebookPickerScenarios.swift",
        "ReaderScenarios.swift",
        "ReaderSelectionTileScenarios.swift",
        "ReviewCalendarScenarios.swift",
        "ReviewFoldScenarios.swift",
        "SelectionToolbarScenarios.swift",
        "SettingsAccountDetailScenarios.swift",
        "SettingsAccountSectionScenarios.swift",
        "SettingsActionsScenarios.swift",
        "SettingsScenarios.swift",
        "SettingsSectionsScenarios.swift",
        "SettingsSubscriptionSectionScenarios.swift",
        "SharedDeckCatalogFixtures.swift",
        "SharedDeckDetailViewScenarios.swift",
        "StatsViewScenarios.swift",
        "SubscriptionViewsScenarios.swift",
        "SyncScenarios.swift",
        "SyncViewScenarios.swift",
        "TodayReviewPhaseScenarios.swift",
        "TodayReviewScenarios.swift",
        "TodayReviewShortcutScenarios.swift",
        "TranslationLanguageSettingsScenarios.swift",
        "VocabActivityHeatmapScenarios.swift",
        "VocabCalendarGridScenarios.swift",
        "VocabComponentScenarios.swift",
        "VocabForecastScenarios.swift",
        "VocabHighlightPickerScenarios.swift",
        "VocabScenarios.swift",
        "VocabSceneShellScenarios.swift",
        "VocabShellChromeScenarios.swift",
        "VocabShellComponentsScenarios.swift",
        "VocabularyListViewScenarios.swift",
        "WelcomeScenarios.swift",
        "WordDetailScenarios.swift",
        "WordEditScenarios.swift",
    }
)


def _world() -> dict:
    return json.loads(WORLD_PATH.read_text(encoding="utf-8"))


def _vocabulary_seed(fixture_id: str) -> dict:
    seed = _world()["vocabulary"].get(fixture_id)
    assert seed is not None, f"UI World 沒有 vocabulary.{fixture_id}"
    return seed


def _visible_entries(seed: dict) -> list[dict]:
    """鏡像 `VocabularyEntry.shouldAppearInKnowledgeList`（isSynced && !delete && !archived）。"""
    return [
        entry
        for entry in seed["entries"]
        if entry.get("syncStatus") == 1 and entry.get("actionType") != "delete" and not entry.get("isArchived")
    ]


def _graph_links(seed: dict) -> list[dict]:
    """鏡像 `UIWorldGraphLinks.makeGraphLinks`：可見 entry 的非隱藏 link，且對端必須也在集合內。"""
    visible = _visible_entries(seed)
    card_ids = {entry["kgCardId"] for entry in visible if entry.get("kgCardId")}
    links: list[dict] = []
    for entry in visible:
        source = entry.get("kgCardId")
        if not source:
            continue
        for summaries in (entry.get("graphLinksByKind") or {}).values():
            for summary in summaries:
                if summary.get("isHidden"):
                    continue
                assert summary["cardId"] in card_ids, (
                    f"graph link {summary['id']} 指向不在可見集合裡的 cardId {summary['cardId']}"
                )
                links.append({"id": summary["id"], "from": source, "to": summary["cardId"]})
    assert len({link["id"] for link in links}) == len(links), "graph link id 必須唯一"
    return links


def _declared_int(source: str, pattern: str, label: str) -> int:
    """抽出唯一一個宣告值；抽不到或抽到多個一律具名失敗，不猜。"""
    matches = re.findall(pattern, source)
    assert len(matches) == 1, f"{label}: 期望剛好一個匹配，實得 {len(matches)}（pattern={pattern!r}）"
    return int(matches[0])


def _screen_id_cases() -> list[str]:
    source = CATALOG_SCENE.read_text(encoding="utf-8")
    enum = re.search(
        r"enum\s+ScreenID\s*:\s*String\s*,\s*CaseIterable\s*\{(?P<body>.*?)\n\s*\}",
        source,
        flags=re.S,
    )
    assert enum, "找不到 CatalogScene.ScreenID 的 CaseIterable enum 區塊"
    declarations = re.findall(
        r"^\s*case\s+([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)",
        enum.group("body"),
        flags=re.M,
    )
    cases = [name for declaration in declarations for name in re.split(r"\s*,\s*", declaration)]
    assert cases, "CatalogScene.ScreenID enum 沒有任何 case"
    return cases


def test_vocabulary_list_marketing_scene_expectation_matches_frozen_world() -> None:
    source = VOCAB_LIST_SCENE.read_text(encoding="utf-8")

    # `Scenario("Reviewed · Marketing")` 用 fixture `.reviewedMarketing`，其
    # `vocabularyID` 映到 `.vocabListPopulated`（同檔的 switch）。兩個錨點都驗，
    # 免得哪天映射改了而門檻沒改，測試卻還對著舊 world 打分。
    mapping = re.search(r"case \.reviewedMarketing:.*?return \.(?P<id>\w+)", source, flags=re.S)
    assert mapping, "找不到 .reviewedMarketing → vocabularyID 的映射"
    fixture_id = mapping.group("id")
    assert fixture_id == "vocabListPopulated", f"映射已改為 {fixture_id}，請一併更新本測試的期望來源"

    declared = _declared_int(
        source,
        r"fixture: \.reviewedMarketing,\s*\n\s*auth: \.signedIn,\s*\n\s*expected: \.visibleAtLeast\((\d+)\)",
        "Reviewed · Marketing 的 visibleAtLeast",
    )
    supply = len(_visible_entries(_vocabulary_seed(fixture_id)))
    assert declared <= supply, (
        f"Reviewed · Marketing 宣告 visibleAtLeast({declared})，但凍結 world "
        f"vocabulary.{fixture_id} 只供得起 {supply} 筆可見 entry"
    )


def test_knowledge_graph_populated_scene_expectations_match_frozen_world() -> None:
    source = GRAPH_SCENE.read_text(encoding="utf-8")

    mapping = re.search(r"case \.populated:\s*\n\s*return \.(?P<id>\w+)", source)
    assert mapping, "找不到 .populated → vocabularyID 的映射"
    fixture_id = mapping.group("id")
    assert fixture_id == "knowledgeGraphPopulated", f"映射已改為 {fixture_id}，請一併更新本測試的期望來源"

    shape = re.search(
        r"return \.init\(\s*visibleEntries: \.atLeast\((?P<entries>\d+)\),\s*"
        r"graphLinks: \.atLeast\((?P<links>\d+)\),\s*"
        r"graphNodes: \.atLeast\((?P<nodes>\d+)\),\s*"
        r"graphEdges: \.atLeast\((?P<edges>\d+)\)\)",
        source,
    )
    assert shape, "找不到 .populated 的四維門檻宣告"

    seed = _vocabulary_seed(fixture_id)
    visible = _visible_entries(seed)
    links = _graph_links(seed)
    # node 上界：可見且有 kgCardId 的 entry（呈現層只會再篩掉孤立節點，不會生出新的）。
    node_ceiling = len([entry for entry in visible if entry.get("kgCardId")])
    # edge 上界：一條 link 至多一條 edge（`edges(from:validNodeIDs:)` 是 compactMap，不複製）。
    edge_ceiling = len(links)

    ceilings = {
        "visibleEntries": (int(shape.group("entries")), len(visible)),
        "graphLinks": (int(shape.group("links")), len(links)),
        "graphNodes": (int(shape.group("nodes")), node_ceiling),
        "graphEdges": (int(shape.group("edges")), edge_ceiling),
    }
    over = {name: pair for name, pair in ceilings.items() if pair[0] > pair[1]}
    assert not over, (
        f"knowledge graph populated scene 宣告的門檻超出凍結 world 的供給："
        + "；".join(f"{name} 宣告 {declared} > 供給 {supply}" for name, (declared, supply) in over.items())
    )


def test_frozen_world_graph_links_are_bidirectional_pairs() -> None:
    """凍結 world 的 link 是雙向成對的——上面兩支測試的供給量依賴這個形狀。

    若哪天有人把 world 改成單向（或半數 hidden），node/edge 的上界會跟著變，
    這條會先講話，而不是讓上面的斷言在無人解讀的情況下鬆掉。
    """
    links = _graph_links(_vocabulary_seed("knowledgeGraphPopulated"))
    degree: Counter[str] = Counter()
    for link in links:
        degree[link["from"]] += 1
        degree[link["to"]] += 1
    assert links, "凍結 world 的 knowledgeGraphPopulated 應該有 graph link"
    assert all(count > 0 for count in degree.values())
    pairs = {frozenset((link["from"], link["to"])) for link in links}
    assert len(pairs) * 2 == len(links), f"link 不再是雙向成對：{len(links)} 條落在 {len(pairs)} 組"


def test_freeze_screen_id_count_does_not_grow() -> None:
    """`docs/reference/catalog_scope.md` §FROZEN 紅線 1、2：凍結期不擴張 catalog。"""
    cases = _screen_id_cases()
    assert len(cases) == FROZEN_SCREEN_ID_COUNT, (
        "凍結期只准降不准升；要升就得同時改這個數字並在 commit 訊息寫明復業理由；"
        f"ScreenID 目前有 {len(cases)} 個 case，baseline 是 {FROZEN_SCREEN_ID_COUNT}"
    )


def test_freeze_debug_scenario_file_set_does_not_grow() -> None:
    """`docs/reference/catalog_scope.md` §FROZEN 紅線 1、2：凍結期不餵既有 scenarios。"""
    current = {path.name for path in SCENARIOS_DIR.glob("*.swift")}
    added = sorted(current - FROZEN_DEBUG_SCENARIO_FILES)
    assert not added, (
        "凍結期只准刪除既有 scenario；要新增檔案就得先復業並更新 baseline："
        + ", ".join(added)
    )
