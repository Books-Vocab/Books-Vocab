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
//  已知限制：XCUITest 的 press-drag 在手指放開後才返回，無法在「按住」期間斷言標記漸入；
//  漸入曲線（連續、單調、閾值飽和）由 TodayReviewSwipeMarkerTests 純函數單元測試鎖定，
//  這裡只驗證放開之後的終態（回彈歸 0、飛出歸 0、卡片照常推進）。
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
            review.dragCard(by: dx)
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
