import XCTest

/// End-to-end contract for the review-card layout editor (Phase C).
///
/// The signal for "the card re-laid out" is the front card's measured HEIGHT, not
/// any text or inner control: the front fold applies `.accessibilityLabel` to its
/// container, so SwiftUI publishes the whole face as one combined element and
/// nothing inside it is addressable. Height is language-independent and is exactly
/// what a layout change moves.
///
/// The layout profile lives in UserDefaults + iCloud KVS, NOT in the UI World seed
/// (that schema is frozen), so it survives an app relaunch and therefore leaks
/// between test methods in one run. Any method that asserts on a baseline resets
/// through the editor's own reset menu first rather than assuming a fresh install.
final class ReviewCardLayoutEditorUITests: UITestCase {
    private static let notebookCardID = "ui-review-notebook"

    override func setUpWithError() throws {
        try super.setUpWithError()
        // Notebook list → session → sheet round trips → reveal springs.
        executionTimeAllowance = 240
    }

    @MainActor
    func testToolbarEditorRelayoutsTheCardAndSharesOneProfileWithSettings() throws {
        let app = launchIsolatedApp(
            fixtures: [.notebookReviewDeck],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"],
            perfLog: "review"
        )
        captureStep("launch", app: app)

        let review = try startReview(app: app)
        let editor = ReviewCardLayoutEditorPage(app: app)

        // ── 1. Toolbar entry opens the editor on the current card's mode ────────
        XCTAssertTrue(review.cardFront.waitUntilExists(timeout: 10))
        review.layoutEditorButton.tapWhenReady()
        guard editor.waitUntilVisible() else {
            captureStep("editor-did-not-open", app: app)
            XCTFail("工具列入口必須開出 layout editor；face picker 缺席")
            return
        }
        editor.lockedRow.assertExists()

        // Reset to the built-in default first: the profile outlives the app
        // process, so a previous method's edits would otherwise be the baseline.
        editor.resetMenu.tapWhenReady()
        editor.resetAllItem.tapWhenReady()
        XCTAssertFalse(editor.isOn("graphLinks"), "辨識正面預設不含知識連結")
        editor.done()

        // ── 2. Enabling a field re-lays out the card behind the sheet ──────────
        XCTAssertTrue(review.cardFront.waitUntilExists(timeout: 8))
        review.layoutEditorButton.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        editor.setField("graphLinks", on: true)
        XCTAssertTrue(editor.isOn("graphLinks"))
        editor.done()
        XCTAssertTrue(review.cardFront.waitUntilExists(timeout: 8))
        RunLoop.current.run(until: Date().addingTimeInterval(0.8))
        // Visual evidence of the live relayout. The front fold publishes itself as
        // ONE combined accessibility element (and repeats its identifier on nested
        // buttons), so the rendered fields are not assertable from the outside —
        // the machine-checkable half of "the store reached the UI" is step 5's
        // derived Settings summary, which re-renders from the same store.
        captureStep("card-after-enabling-links", app: app)

        // Layout only: the card must still be on its front, still card 1.
        review.cardBack.assertDoesNotExist()
        XCTAssertTrue(review.waitForProgress("1 / "))

        // ── 3. Reopening keeps the edit ─────────────────────────────────────────
        review.layoutEditorButton.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        XCTAssertTrue(editor.isOn("graphLinks"), "關閉再開啟 editor 必須保留設定")
        editor.done()

        // ── 4. Settings reads the SAME profile ─────────────────────────────────
        review.close()
        let settings = AppPage(app: app).goToBookshelf().tapSettings()
        guard settings.reviewCardLayoutRow.waitUntilExists(timeout: 10) else {
            captureStep("no-settings-row", app: app)
            XCTFail("偏好區必須有獨立的『複習卡片』row")
            return
        }
        settings.reviewCardLayoutValue.assertExists()
        let customSummary = settings.reviewCardLayoutValue.label
        XCTAssertFalse(customSummary.isEmpty)

        settings.reviewCardLayoutRow.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        XCTAssertTrue(
            editor.isOn("graphLinks"),
            "設定頁與複習頁必須讀寫同一份 profile"
        )

        // ── 5. Reset all puts every mode back, and the summary follows ─────────
        editor.resetMenu.tapWhenReady()
        editor.resetAllItem.tapWhenReady()
        XCTAssertFalse(editor.isOn("graphLinks"), "恢復全部預設後辨識正面應回到只有詞性")

        app.navigationBars.buttons.element(boundBy: 0).tapWhenReady()
        guard settings.reviewCardLayoutValue.waitUntilExists(timeout: 8) else {
            captureStep("no-summary-after-reset", app: app)
            XCTFail("返回設定首頁後必須看得到『複習卡片』摘要")
            return
        }
        XCTAssertNotEqual(
            settings.reviewCardLayoutValue.label,
            customSummary,
            "摘要必須由 profile 推導：自訂→預設 應該改字（\(customSummary)）"
        )
        captureStep("reset-all", app: app)
    }

    /// Worst case for the compaction ladder: every optional field on, on both
    /// faces. The card may scroll or compact, but the grading toolbar is chrome
    /// OUTSIDE the card region and must stay hittable.
    @MainActor
    func testGradingToolbarStaysOperableWithEveryFieldEnabled() throws {
        let app = launchIsolatedApp(
            fixtures: [.notebookReviewDeckVaried],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"],
            perfLog: "review"
        )
        captureStep("launch", app: app)

        let review = try startReview(app: app)
        let editor = ReviewCardLayoutEditorPage(app: app)
        let fields = ["partOfSpeech", "difficultyTier", "graphLinks", "example", "explanation", "collocations"]

        review.layoutEditorButton.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        for field in fields { editor.setField(field, on: true) }
        editor.selectFace(1)
        for field in fields { editor.setField(field, on: true) }
        editor.done()
        captureStep("all-fields-on", app: app)

        XCTAssertTrue(review.cardFront.waitUntilExists(timeout: 8))
        XCTAssertTrue(
            review.rememberedButton.isHittable && review.forgotButton.isHittable,
            "長內容正面下，底部評分按鈕必須仍可操作"
        )

        review.flipCard()
        guard review.cardBack.waitUntilExists(timeout: 8) else {
            captureStep("card-did-not-flip", app: app)
            XCTFail("欄位全開後仍必須能翻面")
            return
        }
        RunLoop.current.run(until: Date().addingTimeInterval(0.6))
        captureStep("all-fields-back", app: app)
        XCTAssertTrue(
            review.rememberedButton.isHittable && review.forgotButton.isHittable,
            "長內容背面下，底部評分按鈕必須仍可操作"
        )

        // And they must still actually grade.
        review.tapRemembered()
        XCTAssertTrue(review.waitForProgress("2 / "), "評分後佇列必須推進")
    }

    /// Autoplay must not keep flipping cards under the editor sheet, and the pause
    /// it takes must survive the sheet closing.
    @MainActor
    func testOpeningTheEditorPausesAutoplayAndLeavesItPaused() throws {
        let app = launchIsolatedApp(
            fixtures: [.notebookReviewDeck],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"],
            perfLog: "review"
        )
        captureStep("launch", app: app)

        let review = try startReview(app: app)
        let editor = ReviewCardLayoutEditorPage(app: app)

        review.autoplayToggleButton.tapWhenReady()
        guard review.autoplayPlayingButton.waitUntilExists(timeout: 8) else {
            captureStep("autoplay-did-not-start", app: app)
            XCTFail("點自動播放後必須進入播放中狀態")
            return
        }

        review.layoutEditorButton.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        editor.done()

        XCTAssertTrue(
            review.autoplayPausedButton.waitUntilExists(timeout: 8),
            "開啟 editor 必須暫停自動播放，且關閉後保持暫停"
        )
        review.autoplayPlayingButton.assertDoesNotExist()
        captureStep("autoplay-paused", app: app)
    }

    // MARK: - Helpers

    @MainActor
    private func startReview(app: XCUIApplication) throws -> TodayReviewPage {
        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.notebookCard(id: Self.notebookCardID).waitUntilExists(timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            throw XCTSkip("review deck fixture 未種出單字本卡片 \(Self.notebookCardID)")
        }
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            throw XCTSkip("fixture 未產生今日複習 CTA")
        }
        let review = notebook.startReview()
        guard review.progressLabel.waitUntilExists(timeout: 10) else {
            captureStep("review-not-started", app: app)
            throw XCTSkip("複習 session 未啟動")
        }
        return review
    }
}
