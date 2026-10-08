//
//  TodayReviewSwipeMarkerUITests.swift
//  Books & Vocab UI Tests
//
//  #2045：卡面「記得 / 忘記」方向標記的端到端判準 —— 標記由 swipeOffset 連續驅動，
//  回彈、飛出（swipe 或按鈕）與 settle 之後都必須歸 0、不留殘影。
//
//  標記在 UITest 進程以 `todayReview.swipeMarker.{remembered,forgot}` 暴露，
//  accessibilityValue = 當下不透明度（"0.00" … "1.00"）。
//
//  XCUITest 的 press-drag 在手指放開後才返回，無法在「按住」期間取樣標記。出現的正控改讀
//  `todayReview.swipeMarkerPeak.*`（UITest-only 探針）：手勢期間各標記的最大強度，放開後保留到
//  下一次手勢；與「放開後歸 0」搭配 = 完整的出現 → 消失判準。標記 / 探針缺席一律 XCTFail，
//  不當成 0。漸入曲線（連續、單調、閾值飽和）由 TodayReviewSwipeMarkerTests 純函數單元測試鎖定。
//

import XCTest

final class TodayReviewSwipeMarkerUITests: UITestCase {
    private static let notebookCardID = "ui-review-notebook"

    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 120
    }

    /// 進入複習並等到評分按鈕就緒（起手狀態：正面、標記皆 0）。
    @MainActor
    private func startReview() throws -> (app: XCUIApplication, review: TodayReviewPage) {
        let app = launchIsolatedApp(
            fixtures: [.notebookReviewDeck],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"]
        )
        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.waitForNotebookCard(id: Self.notebookCardID, timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            XCTFail("notebook.reviewDeck fixture 應種出單字本卡片")
            throw XCTSkip("fixture 未生效")
        }
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            XCTFail("fixture 有未學卡片,今日複習 CTA 必須出現")
            throw XCTSkip("無複習 CTA")
        }
        let review = notebook.startReview()
        XCTAssertTrue(review.progressLabel.waitUntilExists(timeout: 10), "tap CTA 後必須進入複習 session")
        XCTAssertTrue(review.waitForFeedbackControls(timeout: 5), "評分按鈕應 materialize")
        return (app, review)
    }

    /// 等 progress capsule 離開 `initial`（卡片已推進）。輪詢重新解析 query。
    @MainActor
    private func waitForProgressChange(from initial: String, review: TodayReviewPage, timeout: TimeInterval = 8) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if review.progressLabel.exists, review.progressLabel.label != initial { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return review.progressLabel.exists && review.progressLabel.label != initial
    }

    // MARK: - 回彈

    @MainActor
    func testSubThresholdDragSnapsBackAndClearsMarkers() throws {
        let (app, review) = try startReview()
        let initialProgress = review.progressText
        XCTAssertEqual(review.swipeMarkerIntensity(.remembered), 0, "起手標記必須為 0")
        XCTAssertEqual(review.swipeMarkerIntensity(.forgot), 0, "起手標記必須為 0")

        // 閾值 100pt：右、左各拖 60pt（未達閾值）放開 → 回彈、不評分。
        for dx: CGFloat in [60, -60] {
            let shown: TodayReviewPage.SwipeMarker = dx > 0 ? .remembered : .forgot
            let other: TodayReviewPage.SwipeMarker = dx > 0 ? .forgot : .remembered
            review.dragCard(by: dx)
            // 正控：拖動期間對應標記確實漸入（0 < 峰值 < 1，未達閾值不飽和）、反向標記從未出現。
            let peak = review.swipeMarkerPeak(shown)
            XCTAssertGreaterThan(peak, 0.2, "拖動 \(abs(dx))pt 期間對應標記必須漸入（dx=\(dx)）")
            XCTAssertLessThan(peak, 1, "未達閾值標記不得飽和（dx=\(dx)）")
            XCTAssertEqual(review.swipeMarkerPeak(other), 0, "反向標記不得出現（dx=\(dx)）")
            XCTAssertTrue(
                review.waitForSwipeMarkersCleared(timeout: 5),
                "未達閾值放開後標記必須沿回彈淡出歸 0（dx=\(dx)）"
            )
        }
        try step("snapped-back", app: app) {
            XCTAssertEqual(review.progressText, initialProgress, "未達閾值不得評分 / 換卡")
            review.cardFront.assertExists()
        }
    }

    // MARK: - 飛出（swipe）

    @MainActor
    func testPastThresholdSwipeAdvancesCardAndLeavesNoResidualMarker() throws {
        let (app, review) = try startReview()
        let initialProgress = review.progressText

        review.dragCard(by: 220)

        XCTAssertEqual(review.swipeMarkerPeak(.remembered), 1, accuracy: 0.001, "超過閾值右滑期間「記得」必須飽和")
        XCTAssertEqual(review.swipeMarkerPeak(.forgot), 0, "右滑不得出現「忘記」")

        XCTAssertTrue(
            waitForProgressChange(from: initialProgress, review: review),
            "超過閾值右滑放開後卡片必須飛出並推進到下一張"
        )
        try step("swiped-right", app: app) {
            XCTAssertTrue(
                review.waitForSwipeMarkersCleared(timeout: 5),
                "settle 之後標記必須歸 0；殘留 = no-anim transaction 沒把 swipeOffset 歸零"
            )
        }
    }

    // MARK: - 飛出（按鈕）

    @MainActor
    func testButtonFlingLeavesNoResidualMarker() throws {
        let (app, review) = try startReview()

        for button in ["forgot", "remembered"] {
            let before = review.progressText
            if button == "forgot" { review.tapForgot() } else { review.tapRemembered() }
            let (shown, other): (TodayReviewPage.SwipeMarker, TodayReviewPage.SwipeMarker) =
                button == "forgot" ? (.forgot, .remembered) : (.remembered, .forgot)
            XCTAssertEqual(review.swipeMarkerPeak(shown), 1, accuracy: 0.001, "按鈕 fling 對應標記必須沿 fling 漸入到飽和（\(button)）")
            XCTAssertEqual(review.swipeMarkerPeak(other), 0, "按鈕 fling 反向標記不得出現（\(button)）")
            XCTAssertTrue(
                waitForProgressChange(from: before, review: review),
                "按鈕 fling 後卡片必須推進（\(button)）"
            )
            XCTAssertTrue(
                review.waitForSwipeMarkersCleared(timeout: 5),
                "按鈕 fling settle 之後標記必須歸 0（\(button)）"
            )
        }
        captureStep("button-fling-settled", app: app)
    }
}
