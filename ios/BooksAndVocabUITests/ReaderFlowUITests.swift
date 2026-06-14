//
//  ReaderFlowUITests.swift
//  Books & Vocab UI Tests
//
//  Reader 核心 flow（docs/sop/ui_flow_evidence.md 六件套）— 真書 + 視覺證據。
//  Fixture（`-seedFixture:reader:realBookLibrary`）以 lab 真實章節文本
//  （Atomic Habits Introduction，pipeline 抽取的原文）經 app 內 EPUBConverter
//  轉成真 EPUB 入庫，並在綁定單字本內種一筆真詞庫 entry（introduction →
//  引言；導論）。Flow：書架開書 → Readium 渲染真內容 → 選詞 → 翻譯面板
//  帶真內容（詞庫命中路徑，零網路）→ 翻頁進度真前進。
//
//  守門斷言戳破假測試：fixture 該有書卻書架空 = XCTFail（不是 skip）；
//  選詞後沒有面板/沒有內容 = XCTFail。
//

import XCTest

final class ReaderFlowUITests: UITestCase {
    /// 章首獨立成段的真實單字（fixture 詞庫 entry 的 word）。
    private static let seededWord = "Introduction"
    /// UI World 種入詞庫的真翻譯 — 斷言「翻譯 UI 帶內容」的內容本體。
    private static let seededTranslation = "引言"

    private static let fixtureEnvironment: [String: String] = [
        // 詞庫命中路徑不需要網路；指向不可達位址確保任何意外請求
        // connection refused（而非真 backend 401 觸發 session 清除）。
        "KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"
    ]

    override func setUpWithError() throws {
        try super.setUpWithError()
        // 開書（Readium openPublication + 首次 highlight）+ 選詞 + 翻頁，
        // 超過 harness 預設 60s allowance。
        executionTimeAllowance = 120
    }

    @MainActor
    func testReaderOpensRealBookShowsLibraryTranslationAndTurnsPages() throws {
        // authSignedIn 先行：翻譯面板對訪客刻意走 guest 模式（隱藏詞庫翻譯內容），
        // 詞庫命中路徑需要已登入 session（fixture 層解，不在測試裡點登入 —
        // docs/sop/ui_flow_evidence.md 已知 seam）。
        let app = launchIsolatedApp(
            fixtures: [.authSignedIn, .readerRealBookLibrary],
            extraEnvironment: Self.fixtureEnvironment,
            perfLog: "reader"
        )
        captureStep("launch", app: app)

        // ── 1. 書架必須渲染 fixture 種的真書 ────────────────────────────────
        let bookshelf = AppPage(app: app).goToBookshelf()
        guard bookshelf.anyBookCard.waitUntilExists(timeout: 10) else {
            captureStep("no-book-card", app: app)
            XCTFail("reader fixture (realBookLibrary) 應種出一本真書；書架空 = fixture 沒跑或轉檔失敗")
            return
        }
        try step("bookshelf-book-card", app: app) {
            XCTAssertTrue(
                bookshelf.anyBookCard.label.contains("Atomic Habits"),
                "書卡 label 應含 fixture 書名，got: \(bookshelf.anyBookCard.label)"
            )
        }

        // ── 2. 開書 → Readium 真的渲染章節原文 ──────────────────────────────
        let reader = ReaderPage(app: app)
        try step("book-opened", app: app) {
            bookshelf.anyBookCard.tapWhenReady()
        }
        guard reader.contentText(Self.seededWord).waitUntilExists(timeout: 45) else {
            captureStep("reader-content-missing", app: app)
            XCTFail("閱讀器必須渲染真章節文本（章首段落「\(Self.seededWord)」）— 沒出現 = 開書失敗或內容是假的")
            return
        }
        captureStep("reader-content", app: app)

        // ── 3. 選詞 → 翻譯面板真的出現且帶內容（詞庫命中，零網路）──────────
        try step("word-tapped", app: app) {
            reader.contentText(Self.seededWord).tapWhenReady()
        }
        guard reader.translationPanel.waitUntilExists(timeout: 5) else {
            captureStep("no-translation-panel", app: app)
            XCTFail("點擊單字後翻譯面板必須出現 — 沒出現 = 選詞橋接或 overlay 壞了")
            return
        }
        XCTAssertTrue(
            reader.translationWord.waitUntilLabelContains(Self.seededWord, timeout: 5),
            "面板 headword 必須是被點的單字，got: \(reader.translationWord.exists ? reader.translationWord.label : "<missing>")"
        )
        XCTAssertTrue(
            reader.translationText.waitUntilLabelContains(Self.seededTranslation, timeout: 5),
            "面板必須帶真翻譯內容（fixture 詞庫 entry），got: \(reader.translationText.exists ? reader.translationText.label : "<missing>")"
        )
        captureStep("translation-shown", app: app)

        // ── 4. 關閉面板（真狀態收回）────────────────────────────────────────
        try step("translation-dismissed", app: app) {
            reader.translationDismissButton.tapWhenReady()
            XCTAssertTrue(
                reader.translationPanel.waitUntilGone(timeout: 5),
                "點 dismiss 後翻譯面板必須收回"
            )
        }

        // ── 5. 翻頁 → 進度徽章數值真前進 ────────────────────────────────────
        let initialProgress = reader.progressPercent() ?? 0
        try step("page-turned", app: app) {
            reader.webView.swipeLeft()
            XCTAssertTrue(
                reader.waitUntilProgressExceeds(initialProgress, timeout: 10),
                """
                翻頁後 header 進度徽章必須顯示更高的 totalProgression \
                （before=\(initialProgress)%, after=\(reader.progressPercent().map(String.init(describing:)) ?? "<missing>")）\
                — 沒前進 = 只滑了手勢、頁面沒真的翻
                """
            )
        }
        attachText(
            """
            fixtureDataset=marketing_demo
            readerFixture=realBookLibrary
            seededWord=\(Self.seededWord)
            seededTranslation=\(Self.seededTranslation)
            progressBefore=\(initialProgress)
            progressAfter=\(reader.progressPercent().map(String.init(describing:)) ?? "<missing>")
            """,
            named: "Reader Flow Metrics"
        )
    }
}
