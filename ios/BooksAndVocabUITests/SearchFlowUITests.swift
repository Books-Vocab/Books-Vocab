//
//  SearchFlowUITests.swift
//  Books & Vocab UI Tests
//
//  詞庫搜尋 flow（app 內唯一主線搜尋面）— 真資料 + 視覺證據，照
//  docs/sop/ui_flow_evidence.md 的 Podcast 活樣板。
//
//  核心真行為：fixture 種真詞條（curated demo vocabulary：affect / effect /
//  complement / compliment / …，真譯文真例句）→ notebook 鑽入詞庫列表 →
//  輸入查詢 → 結果集「真的」只剩匹配項（compl → complement+compliment、
//  affect 消失）→ 清空回完整列表 → 無結果查詢落 empty state（不沉默）→
//  點一筆結果 → word detail hero word 與該筆一致。
//  Fixture: `-seedFixture:search:vocabNotebook`（已登入 session + 真詞條
//  notebook；搜尋框只在登入態顯示）。
//

import XCTest

final class SearchFlowUITests: UITestCase {
    private static let notebookId = "ui-search-notebook"

    override func setUpWithError() throws {
        try super.setUpWithError()
        // Drill-down + 三輪查詢（含 debounce 等待）+ detail 開啟，超過 harness
        // 預設 60s allowance（ops/ios_test.sh，上限 120）。
        executionTimeAllowance = 120
    }

    @MainActor
    func testVocabularySearchFiltersRealEntriesAndOpensMatchingDetail() throws {
        let app = launchIsolatedApp(
            fixtures: [.searchVocabNotebook],
            extraEnvironment: [
                // 假 token 不可打真 backend：api/health 401 會觸發 logout +
                // clearLocalData 把 fixture 世界清掉（同 AuthFlowUITests）。
                "KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"
            ],
            perfLog: "search"
        )
        captureStep("launch", app: app)

        let search = VocabularySearchPage(app: app)
        let auth = AuthPage(app: app)

        // ── 1. Notebook tab → seeded notebook card ───────────────────────────
        try step("notebook-list", app: app) {
            AppPage(app: app).goToNotebooks()
            XCTAssertTrue(app.waitForNavigationToSettle())
            guard NotebookPage(app: app).notebookCard(id: Self.notebookId)
                .waitUntilExists(timeout: 10) else {
                captureStep("no-notebook-card", app: app)
                XCTFail("search fixture 必須種出 notebook card \(Self.notebookId) — fixture 未生效")
                return
            }
        }

        // ── 2. Drill into the vocabulary list ────────────────────────────────
        try step("vocab-list-opened", app: app) {
            NotebookPage(app: app).notebookCard(id: Self.notebookId).tapWhenReady()
            XCTAssertTrue(app.waitForNavigationToSettle())
        }

        // 守門：fixture 已注入登入 session，login gate 出現 = 測的不是搜尋。
        if auth.loginSheet.waitUntilExists(timeout: 1) {
            captureStep("unexpected-login-sheet", app: app)
            XCTFail("search fixture 已登入 — login sheet 出現代表 fixture 沒有真的登入")
            return
        }

        // ── 3. 搜尋框 + 真詞條列表都必須渲染（fixture 該有資料卻沒有 = fail）──
        guard search.searchField.waitUntilExists(timeout: 10) else {
            captureStep("no-search-field", app: app)
            XCTFail("已登入 fixture 必須顯示搜尋框（vocab.searchField）")
            return
        }
        guard search.anyRow.waitUntilExists(timeout: 10) else {
            captureStep("no-vocab-rows", app: app)
            XCTFail("fixture 種了真實詞條卻一筆都沒渲染 — 搜尋前提不成立")
            return
        }
        captureStep("vocab-list-ready", app: app)

        // ── 4. 查詢 "compl" → 結果集真的只剩匹配項 ───────────────────────────
        try step("search-compl-results", app: app) {
            search.search("compl")
            XCTAssertTrue(
                search.row(word: "complement").waitUntilExists(timeout: 5),
                "查 compl 必須命中 complement（word contains）"
            )
            XCTAssertTrue(
                search.row(word: "compliment").waitUntilExists(timeout: 5),
                "查 compl 必須命中 compliment（word contains）"
            )
            XCTAssertTrue(
                search.row(word: "affect").waitUntilGone(timeout: 5),
                "查 compl 後不匹配的 affect 必須從結果消失 — 否則搜尋沒有真的過濾"
            )
            XCTAssertFalse(
                search.row(word: "ambiguous").exists,
                "查 compl 後不匹配的 ambiguous 不得殘留"
            )
        }

        // ── 5. 清空查詢（防呆步）→ 完整列表回來 ──────────────────────────────
        try step("search-cleared", app: app) {
            search.clearSearch()
            XCTAssertTrue(
                search.anyRowNotContaining("compl").waitUntilExists(timeout: 5),
                "清空搜尋後完整列表必須回來（compl 以外的詞條重新出現）"
            )
        }

        // ── 6. 無結果查詢（防呆步）→ empty state，不沉默 ─────────────────────
        try step("search-no-result", app: app) {
            search.search("zzqxv")
            XCTAssertTrue(
                search.emptySearchStateTitle.waitUntilExists(timeout: 5),
                "無結果查詢必須顯示「沒有符合的單字」empty state"
            )
            XCTAssertTrue(
                search.anyRow.waitUntilGone(timeout: 5),
                "無結果查詢後不得殘留任何詞條 row"
            )
        }

        // ── 7. 精準重查 + 點開 detail → 內容對應該筆 ─────────────────────────
        try step("search-complement-requery", app: app) {
            search.clearSearch()
            search.search("complement")
            XCTAssertTrue(
                search.row(word: "complement").waitUntilExists(timeout: 5),
                "查 complement 必須命中該詞條"
            )
            XCTAssertTrue(
                search.row(word: "compliment").waitUntilGone(timeout: 5),
                "查 complement 不得命中 compliment（contains 不成立）"
            )
        }
        try step("detail-opened", app: app) {
            search.row(word: "complement").tapWhenReady()
            guard search.detailHeroWord.waitUntilExists(timeout: 5) else {
                captureStep("no-detail-hero", app: app)
                XCTFail("點擊搜尋結果後必須開啟 word detail（cardDocument.hero.word 未出現）")
                return
            }
            XCTAssertEqual(
                search.detailHeroWord.label,
                "complement",
                "word detail hero 必須對應點擊的那筆搜尋結果"
            )
        }
        captureStep("detail-verified", app: app)
    }
}
