import XCTest

/// #2044: the review card's add-link control must offer at least a 44×44pt hit
/// target in both shapes — the "+" at the end of the link strip and the empty
/// state's "+ Add link" prompt — while staying a single, tappable element.
final class TodayReviewAddLinkHitTargetUITests: UITestCase {
    private static let minimumSide: CGFloat = 44

    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 180
    }

    @MainActor
    private func revealedReview(_ app: XCUIApplication) -> TodayReviewPage? {
        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            XCTFail("fixture 有到期卡片，複習 CTA 必須出現")
            return nil
        }
        let review = notebook.startReview()
        guard review.progressLabel.waitUntilExists(timeout: 10),
              review.waitForFeedbackControls(timeout: 5) else {
            captureStep("review-not-started", app: app)
            XCTFail("tap CTA 後必須進入複習 session")
            return nil
        }
        review.flipCard()
        guard review.cardBack.waitUntilExists(timeout: 5),
              review.addLinkButton.waitUntilExists(timeout: 10) else {
            captureStep("add-link-missing", app: app)
            XCTFail("翻卡後背面必須有新增連結入口")
            return nil
        }
        review.assertAddLinkButtonIsUnique()
        return review
    }

    @MainActor
    private func assertHitTargetAndTap(_ app: XCUIApplication, review: TodayReviewPage) {
        let frame = review.addLinkButton.frame
        XCTAssertGreaterThanOrEqual(frame.width, Self.minimumSide, "新增連結可點寬度必須 ≥44pt，實得 \(frame.width)")
        XCTAssertGreaterThanOrEqual(frame.height, Self.minimumSide, "新增連結可點高度必須 ≥44pt，實得 \(frame.height)")
        captureStep("add-link-hit-target", app: app)

        // Tap near the top edge of the enlarged target — outside the glyph
        // itself — to prove the extra area is really hittable.
        review.addLinkButton.coordinate(withNormalizedOffset: CGVector(dx: 0.5, dy: 0.1)).tap()
        XCTAssertTrue(
            app.textFields["addLink.searchField"].waitUntilExists(timeout: 10),
            "點擊放大後的可點範圍邊緣必須開啟 AddLink sheet"
        )
        app.buttons["addLink.cancel"].tapWhenReady()
    }

    /// Link strip shape: the first card of the multi-notebook deck has a link.
    @MainActor
    func testLinkStripPlusHasAtLeast44ptHitTarget() throws {
        let app = launchIsolatedApp(fixtures: [.notebookReviewDeckMultiNotebook], perfLog: "review")
        guard let review = revealedReview(app) else { return }
        // Positive control: the strip (not the empty prompt) is what is measured.
        // The card cache shuffles which links sit beside the label, so match any
        // fixture link rather than one id.
        let shownLinks = app.descendants(matching: .any).matching(
            NSPredicate(format: "identifier BEGINSWITH %@", "todayReview.card.link.multinb-")
        )
        XCTAssertGreaterThan(
            shownLinks.count,
            0,
            "首張卡必須畫出連結列，量到的才是列尾的「＋」"
        )
        assertHitTargetAndTap(app, review: review)
    }

    /// Empty-state shape: the varied deck has no links, so the prompt is shown.
    @MainActor
    func testEmptyAddLinkPromptHasAtLeast44ptHitTarget() throws {
        let app = launchIsolatedApp(fixtures: [.notebookReviewDeckVaried], perfLog: "review")
        guard let review = revealedReview(app) else { return }
        XCTAssertEqual(
            app.descendants(matching: .any).matching(NSPredicate(format: "identifier BEGINSWITH %@", "todayReview.card.link.")).count,
            0,
            "positive control：無連結卡量到的必須是空狀態入口"
        )
        assertHitTargetAndTap(app, review: review)
    }
}
