import XCTest

private struct ReviewCardVisualEvidenceCapture {
    let assetID: String
    let fixture: UITestFixture
    let identity: TodayReviewPage.CardIdentity
    let face: TodayReviewPage.CardFace
    let presentation: TodayReviewPage.CardPresentation
    let geometry: TodayReviewPage.CardGeometryContract

    var readiness: TodayReviewPage.EvidenceReadinessContract {
        TodayReviewPage.EvidenceReadinessContract(
            face: face,
            identity: identity,
            presentation: presentation,
            geometry: geometry
        )
    }
}

private enum ReviewCardVisualEvidenceStep {
    static let optionalSectionsCounterexample = ReviewCardVisualEvidenceCapture(
        assetID: "optional-sections-counterexample",
        fixture: .notebookReviewCardCompactCounterexample,
        identity: .p12CompactCoaxedRecognition,
        face: .front,
        presentation: .natural,
        geometry: .compactFront
    )

    static let smallViewportCounterexample = ReviewCardVisualEvidenceCapture(
        assetID: "small-viewport-counterexample",
        fixture: .notebookReviewCardFullInfo,
        identity: .p13Production,
        face: .back,
        presentation: .scroll,
        geometry: .fullBack
    )

    static let compactBackCounterexample = ReviewCardVisualEvidenceCapture(
        assetID: "compact-back-counterexample",
        fixture: .notebookReviewCardCompactCounterexample,
        identity: .p12CompactCoaxedRecognition,
        face: .back,
        presentation: .natural,
        geometry: .compactBack
    )

    static let largeTextCounterexample = ReviewCardVisualEvidenceCapture(
        assetID: "large-text-counterexample",
        fixture: .notebookReviewCardFullInfo,
        identity: .p13Production,
        face: .front,
        presentation: .scroll,
        geometry: .fullFront
    )
}

private enum ReviewCardLayoutEditorUITestError: Error {
    case preconditionFailed
}

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
            fixtures: [ReviewCardVisualEvidenceStep.optionalSectionsCounterexample.fixture],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"],
            perfLog: "review"
        )
        captureStep("launch", app: app)

        let review = try startReview(app: app)
        let optionalCapture = ReviewCardVisualEvidenceStep.optionalSectionsCounterexample
        let editor = ReviewCardLayoutEditorPage(app: app)

        // ── 1. Toolbar entry opens the editor ──────────────────────────────────
        XCTAssertTrue(review.waitForUnique("todayReview.card.front", timeout: 10))
        review.layoutEditorButton.tapWhenReady()
        guard editor.waitUntilVisible() else {
            captureStep("editor-did-not-open", app: app)
            XCTFail("工具列入口必須開出 layout editor；方向 preset picker 缺席")
            return
        }
        editor.previewCard.assertExists()

        // Reset to the built-in default first: the profile outlives the app
        // process, so a previous method's edits would otherwise be the baseline.
        editor.resetAll()
        XCTAssertTrue(
            editor.isPresetSelected("recognition", index: ReviewCardLayoutEditorPage.PresetIndex.standard),
            "恢復全部預設後辨識方向應該停在「正常」"
        )
        editor.done()

        // ── 2. Switching to 精簡 re-lays out the card behind the sheet ─────────
        XCTAssertTrue(review.waitForUnique("todayReview.card.front", timeout: 8))
        review.layoutEditorButton.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        editor.selectPreset("recognition", index: ReviewCardLayoutEditorPage.PresetIndex.compact)
        editor.selectPreset("production", index: ReviewCardLayoutEditorPage.PresetIndex.compact)
        XCTAssertTrue(
            editor.isPresetSelected("recognition", index: ReviewCardLayoutEditorPage.PresetIndex.compact)
        )
        editor.done()
        guard captureCanonicalStep(optionalCapture, review: review, app: app) else { return }

        // Layout only: the card must still be on its front, still card 1.
        review.assertCardBackDoesNotExist()
        XCTAssertTrue(review.waitForProgress("1 / "))

        // ── 3. Reopening keeps the edit ─────────────────────────────────────────
        review.layoutEditorButton.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        XCTAssertTrue(
            editor.isPresetSelected("recognition", index: ReviewCardLayoutEditorPage.PresetIndex.compact),
            "關閉再開啟 editor 必須保留精簡設定"
        )
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

        settings.openReviewCardLayout()
        XCTAssertTrue(editor.waitUntilVisible())
        XCTAssertTrue(
            editor.isPresetSelected("recognition", index: ReviewCardLayoutEditorPage.PresetIndex.compact),
            "設定頁與複習頁必須讀寫同一份 profile"
        )

        // ── 5. Reset all puts every mode back, and the summary follows ─────────
        editor.resetAll()
        XCTAssertTrue(
            editor.isPresetSelected("recognition", index: ReviewCardLayoutEditorPage.PresetIndex.standard),
            "恢復全部預設後應回到正常版面"
        )

        settings.goBack()
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

    /// Worst case for the compaction ladder: both directions on 正常, which is the
    /// richest face the preset model can produce. The card may scroll or compact,
    /// but the grading toolbar is chrome OUTSIDE the card region and must stay
    /// hittable.
    @MainActor
    func testGradingToolbarStaysOperableWithEveryFieldEnabled() throws {
        let app = launchIsolatedApp(
            extraArgs: ["-reviewCardDynamicType", "accessibility3"],
            fixtures: [ReviewCardVisualEvidenceStep.largeTextCounterexample.fixture],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"],
            perfLog: "review"
        )
        captureStep("launch", app: app)

        let review = try startReview(app: app)
        let frontCapture = ReviewCardVisualEvidenceStep.largeTextCounterexample
        let backCapture = ReviewCardVisualEvidenceStep.smallViewportCounterexample
        let editor = ReviewCardLayoutEditorPage(app: app)

        review.layoutEditorButton.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        editor.selectPreset("recognition", index: ReviewCardLayoutEditorPage.PresetIndex.standard)
        editor.selectPreset("production", index: ReviewCardLayoutEditorPage.PresetIndex.standard)
        editor.previewCard.assertExists()
        editor.done()
        guard captureCanonicalStep(frontCapture, review: review, app: app) else { return }
        XCTAssertTrue(
            review.rememberedButton.isHittable && review.forgotButton.isHittable,
            "長內容正面下，底部評分按鈕必須仍可操作"
        )

        review.flipCard()
        guard review.waitForUnique("todayReview.card.back", timeout: 8) else {
            captureStep("\(backCapture.assetID).not-mounted", app: app)
            XCTFail("欄位全開後仍必須能翻面")
            return
        }
        guard captureCanonicalStep(backCapture, review: review, app: app) else { return }
        XCTAssertTrue(
            review.rememberedButton.isHittable && review.forgotButton.isHittable,
            "長內容背面下，底部評分按鈕必須仍可操作"
        )

        // And they must still actually grade.
        review.tapRemembered()
        XCTAssertTrue(review.waitForProgress("2 / "), "評分後佇列必須推進")
    }

    @MainActor
    func testCompactCounterexampleUsesCanonicalSeedAndHidesOnlyOptionalFields() throws {
        let app = launchIsolatedApp(
            extraArgs: ["-reviewCardDynamicType", "accessibility3"],
            fixtures: [ReviewCardVisualEvidenceStep.compactBackCounterexample.fixture],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"],
            perfLog: "review"
        )
        captureStep("launch", app: app)

        let review = try startReview(app: app)
        let compactBackCapture = ReviewCardVisualEvidenceStep.compactBackCounterexample
        let editor = ReviewCardLayoutEditorPage(app: app)
        review.layoutEditorButton.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        editor.selectPreset("recognition", index: ReviewCardLayoutEditorPage.PresetIndex.compact)
        editor.selectPreset("production", index: ReviewCardLayoutEditorPage.PresetIndex.compact)
        editor.done()

        review.flipCard()
        guard review.waitForUnique("todayReview.card.back", timeout: 8) else {
            captureStep("\(compactBackCapture.assetID).not-mounted", app: app)
            XCTFail("P12 compact 背面 evidence 必須先掛載 back face")
            return
        }
        guard captureCanonicalStep(compactBackCapture, review: review, app: app) else { return }
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
        guard review.waitForUnique("todayReview.autoplay.playing", timeout: 8) else {
            captureStep("autoplay-did-not-start", app: app)
            XCTFail("點自動播放後必須進入播放中狀態")
            return
        }

        review.layoutEditorButton.tapWhenReady()
        XCTAssertTrue(editor.waitUntilVisible())
        editor.done()

        XCTAssertTrue(
            review.waitForUnique("todayReview.autoplay.paused", timeout: 8),
            "開啟 editor 必須暫停自動播放，且關閉後保持暫停"
        )
        review.assertAutoplayPlayingDoesNotExist()
        captureStep("autoplay-paused", app: app)
    }

    // MARK: - Helpers

    @MainActor
    private func startReview(app: XCUIApplication) throws -> TodayReviewPage {
        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.notebookCard(id: Self.notebookCardID).waitUntilExists(timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            XCTFail("review deck fixture 未種出單字本卡片 \(Self.notebookCardID)")
            throw ReviewCardLayoutEditorUITestError.preconditionFailed
        }
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            XCTFail("fixture 未產生今日複習 CTA")
            throw ReviewCardLayoutEditorUITestError.preconditionFailed
        }
        let review = notebook.startReview()
        guard review.waitForUnique("todayReview.progressLabel", timeout: 10) else {
            captureStep("review-not-started", app: app)
            XCTFail("複習 session 未啟動")
            throw ReviewCardLayoutEditorUITestError.preconditionFailed
        }
        return review
    }

    private func captureCanonicalStep(
        _ capture: ReviewCardVisualEvidenceCapture,
        review: TodayReviewPage,
        app: XCUIApplication
    ) -> Bool {
        guard review.waitForEvidenceReadiness(capture.readiness, timeout: 8) else {
            captureStep("\(capture.assetID).not-ready.\(capture.identity.cardID)", app: app)
            XCTFail(
                "\(capture.assetID) readiness failed for \(capture.face.rawValue) "
                    + "\(capture.identity.cardID)/\(capture.identity.frontWord)"
            )
            return false
        }
        captureStep("\(capture.assetID).\(capture.identity.cardID)", app: app)
        return true
    }
}
