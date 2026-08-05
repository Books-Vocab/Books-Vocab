//
//  TodayReviewAutoplayChromeUITests.swift
//  Books & Vocab UI Tests
//
//  端到端證明「播放模式按下即變」——機制綠(單元測試)不等於視覺對,這條走真實
//  chrome 切換。對應使用者回報:進入播放模式有延遲、按第二下出不去。
//
//  兩個判準都刻意做成**與計時無關**:
//
//  1. ON 方向(結構性判準,非 timeout 賭博):autoplay loop 的第一個動作是翻面,
//     而翻面 mutate 的 `session` 正是修復前唯一能讓 body 重評的東西——所以修復前
//     「toolbar 換成播放列」與「卡片翻面」必定發生在同一幀。斷言 toolbar 已換掉
//     **而卡片仍未翻面**(`cardBack` 不存在),修復前不可能成立,和機器快慢無關。
//
//  2. OFF 方向(無可爭議):關閉 autoplay 後 loop 已死,修復前沒有任何東西能再觸發
//     重繪,「忘記/記得」按鈕**永遠**不會回來。給多長 timeout 都不會假綠。
//
//  設計上刻意避開的兩個坑(第一版就是踩在這裡):
//    - **不靠 a11y label 選播放鍵**:它會在「開啟/關閉自動播放」之間翻轉,狀態切換
//      的瞬間選不到。改用穩定的 `todayReview.autoplayToggle` identifier。
//    - **不讓 autoplay 自己活太久**:量測與截圖全部延後到兩次點擊都完成之後,
//      OFF 緊接在 ON 判定之後(仍在第一次翻面的 2s 之內),測試就不受 loop 推進、
//      末卡自停等生命週期事件干擾。
//

import XCTest

final class TodayReviewAutoplayChromeUITests: UITestCase {
    private static let notebookCardID = "ui-review-notebook"
    /// L10n `todayReview.autoplay.playpause.pause` —— 只在播放列上存在。
    private static let pauseLabel = "暫停自動播放"

    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 120
    }

    @MainActor
    func testAutoplayChromeSwapsImmediatelyInBothDirections() throws {
        let app = launchIsolatedApp(
            fixtures: [.notebookReviewDeck],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"],
            perfLog: "review"
        )
        captureStep("launch", app: app)

        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.notebookCard(id: Self.notebookCardID).waitUntilExists(timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            XCTFail("notebook.reviewDeck fixture 應種出單字本卡片；列表空狀態 = fixture 未生效")
            return
        }
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            XCTFail("fixture 有未學卡片,今日複習 CTA 必須出現")
            return
        }
        let review = notebook.startReview()

        guard review.progressLabel.waitUntilExists(timeout: 10) else {
            captureStep("review-not-started", app: app)
            XCTFail("tap CTA 後必須進入複習 session")
            return
        }

        let autoplayToggle = app.descendants(matching: .any)
            .matching(identifier: "todayReview.autoplayToggle").firstMatch
        try step("review-started", app: app) {
            review.rememberedButton.assertExists()
            XCTAssertFalse(review.cardBack.exists, "起手不得已翻面")
            XCTAssertTrue(autoplayToggle.waitUntilExists(timeout: 5), "top bar 必須有播放鍵")
        }

        // ── 兩次點擊之間不做任何截圖/斷言,量測全部延後 ────────────────────
        // ON:toolbar 必須在卡片翻面「之前」就換成播放列。
        autoplayToggle.tap()
        let swappedToAutoplay = Self.waitUntil(timeout: 1.5) { !review.rememberedButton.exists }
        let flippedDuringSwap = review.cardBack.exists
        let transportShown = app.buttons[Self.pauseLabel].exists

        // OFF:緊接著再按一次(仍在第一次 reveal 的 2s 窗內,不受 loop 推進干擾)。
        autoplayToggle.tap()
        let restoredFeedback = Self.waitUntil(timeout: 5) { review.rememberedButton.exists }
        let transportGone = !app.buttons[Self.pauseLabel].exists

        try step("autoplay-toggled-both-ways", app: app) {
            XCTAssertTrue(
                swappedToAutoplay,
                "按下播放後 1.5s 內 toolbar 仍是評分按鈕 = chrome 沒跟上 autoplay 狀態"
            )
            XCTAssertFalse(
                flippedDuringSwap,
                "chrome 直到卡片翻面才切換 = 它是被 loop 的 session mutation 帶起來的,"
                + " 不是被 autoplay 狀態本身通知的(observation 斷鏈的指紋)"
            )
            XCTAssertTrue(transportShown, "播放列(暫停鍵)必須在 chrome 切換的同時就位")
            XCTAssertTrue(
                restoredFeedback,
                "關閉 autoplay 後評分按鈕沒有回來 —— loop 已停,不會有任何後續事件救它,"
                + " 這就是使用者回報的「按了沒反應、出不去」"
            )
            XCTAssertTrue(transportGone, "播放列必須完全收起")
        }
    }

    // MARK: - Helpers

    /// Poll-based condition wait(重新解析 query,避免讀到陳舊的 a11y snapshot,
    /// 與 `TodayReviewPage.waitUntilLabel` 同模式)。
    @MainActor
    private static func waitUntil(timeout: TimeInterval, _ condition: () -> Bool) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return condition()
    }
}
