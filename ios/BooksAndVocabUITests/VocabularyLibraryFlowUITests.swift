import XCTest

/// P11 acceptance flow: the report baseline injects 644 ordinary reviewable
/// rows. Its review buckets are 14/503/127 and its CTA is 517.
final class VocabularyLibraryFlowUITests: UITestCase {
    private static let notebookID = "ui-p11-644-review-mix-notebook"

    override func setUpWithError() throws {
        try super.setUpWithError()
        XCUIDevice.shared.orientation = .portrait
        // The canonical 644-row UI World is intentionally a large-data
        // acceptance path; its measured cold launch and AX queries exceed the
        // generic smoke allowance. The allowance belongs to XCTest itself.
        executionTimeAllowance = 360
    }

    @MainActor
    func testRichWorldProjectsReviewSearchAndCTAConsistently() throws {
        let app = launchIsolatedApp(
            extraArgs: [
                "-UIPreferredContentSizeCategoryName",
                "UICTContentSizeCategoryAccessibility3",
            ],
            fixtures: [.vocabularyLibraryP11ReviewMix],
            extraEnvironment: [
                "KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"
            ],
            perfLog: "vocabulary-filter-rich"
        )
        captureStep("launch", app: app)

        let shell = AppPage(app: app)
        let notebooks = shell.goToNotebooks()
        guard notebooks.notebookCard(id: Self.notebookID).waitUntilExists(timeout: 10) else {
            captureStep("no-rich-notebook", app: app)
            XCTFail("rich vocabulary UI World 必須種出 notebook \(Self.notebookID)")
            return
        }
        captureStep("notebook-ready", app: app)

        notebooks.notebookCard(id: Self.notebookID).tapWhenReady()
        let page = VocabularySearchPage(app: app)
        // The direct count probe avoids an O(N) accessibility-tree query for a
        // 644-row LazyVStack. Individual rows are asserted after each
        // projection where their lazy materialization is deterministic.
        guard page.visibleCount.waitUntilExists(timeout: 20) else {
            captureStep("no-rich-vocabulary-rows", app: app)
            XCTFail("rich fixture 必須渲染 vocabulary rows")
            return
        }
        captureStep("vocabulary-list-open", app: app)
        XCTAssertTrue(page.visibleCount.waitUntilExists(timeout: 5))
        captureStep("all-644-rows", app: app)
        page.assertVisibleCount(644, message: "review-state projection must show 644 visible rows")
        XCTAssertTrue(page.reviewCTA.waitUntilExists(timeout: 5), "report baseline CTA must be visible")
        XCTAssertEqual(page.reviewCTAValue, 517, "report baseline CTA must be exactly 517")
        XCTAssertTrue(page.sortMenu.waitUntilExists(timeout: 5), "sort control must remain a separate semantic control")
        XCTAssertEqual(page.reviewStateCount("unlearned", labelPrefix: "未學習"), 14)
        XCTAssertEqual(page.reviewStateCount("due", labelPrefix: "待複習"), 503)
        XCTAssertEqual(page.reviewStateCount("reviewed", labelPrefix: "已複習"), 127)
        XCTAssertTrue(page.reviewCTA.isHittable, "CTA must remain hittable at accessibility3")
        XCTAssertTrue(page.sortMenu.isHittable, "sort must remain hittable at accessibility3")
        captureStep("dynamic-type", app: app)
        captureStep("cta", app: app)

        try step("review-state", app: app) {
            XCTAssertTrue(page.reviewStateControls.waitUntilExists(timeout: 5))
            page.assertVisibleCount(644, message: "review-state projection must show all ordinary cards")
            XCTAssertTrue(page.reviewStateOption("unlearned", labelPrefix: "未學習").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.reviewStateOption("due", labelPrefix: "待複習").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.reviewStateOption("reviewed", labelPrefix: "已複習").waitUntilExists(timeout: 5))
            XCTAssertEqual(page.reviewStateCount("unlearned", labelPrefix: "未學習"), 14)
            XCTAssertEqual(page.reviewStateCount("due", labelPrefix: "待複習"), 503)
            XCTAssertEqual(page.reviewStateCount("reviewed", labelPrefix: "已複習"), 127)
            captureStep("review-state-filter-open", app: app)
            page.selectReviewState("unlearned", labelPrefix: "未學習")
            page.assertVisibleCount(14)
            XCTAssertTrue(page.row(word: "p11-review-word-001").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.row(word: "p11-review-word-015").waitUntilGone(timeout: 5))
            page.selectReviewState("due", labelPrefix: "待複習")
            page.assertVisibleCount(517, message: "multi-select must union 14 unlearned and 503 due rows")
            XCTAssertTrue(
                page.reviewStateOption("unlearned", labelPrefix: "未學習").isSelected,
                "union must retain the unlearned review-state selection"
            )
            XCTAssertTrue(
                page.reviewStateOption("due", labelPrefix: "待複習").isSelected,
                "union must add the due review-state selection"
            )
            page.search("p11-review-word-001")
            page.assertVisibleCount(1, message: "union must retain an unlearned row")
            XCTAssertTrue(page.waitForRowMaterialized(word: "p11-review-word-001"))
            page.clearSearch()
            page.assertVisibleCount(517)
            page.search("p11-review-word-015")
            page.assertVisibleCount(1, message: "union must include a due row")
            XCTAssertTrue(page.waitForRowMaterialized(word: "p11-review-word-015"))
            page.clearSearch()
            page.assertVisibleCount(517)
        }

        try step("reviewed-scope", app: app) {
            page.clearReviewStates()
            page.selectReviewState("reviewed", labelPrefix: "已複習")
            page.assertVisibleCount(127)
            page.search("p11-review-word-518")
            page.assertVisibleCount(1, message: "reviewed facet must project a reviewed row")
            XCTAssertTrue(page.waitForRowMaterialized(word: "p11-review-word-518"))
            page.clearSearch()
            page.assertVisibleCount(127)
        }

        try step("search-within-projection", app: app) {
            page.clearReviewStates()
            page.search("p11-review-word-001")
            page.assertVisibleCount(1, message: "search visible count must be independent from facet counts")
            XCTAssertTrue(page.waitForRowMaterialized(word: "p11-review-word-001"))
            XCTAssertTrue(page.row(word: "p11-review-word-015").waitUntilGone(timeout: 5))
            XCTAssertEqual(page.reviewStateCount("unlearned", labelPrefix: "未學習"), 14)
            XCTAssertEqual(page.reviewStateCount("due", labelPrefix: "待複習"), 503)
            XCTAssertEqual(page.reviewStateCount("reviewed", labelPrefix: "已複習"), 127)
            page.clearSearch()
            page.assertVisibleCount(644)
            // Clearing a query restores the full projection without resetting
            // LazyVStack's scroll position. Assert the projection count and a
            // materialized non-query row instead of assuming row 015 is in the
            // current viewport.
            XCTAssertTrue(
                page.anyRowNotContaining("p11-review-word-001").waitUntilExists(timeout: 5),
                "clearing search must materialize a row outside the previous query"
            )
        }

        captureStep("rich-projection-verified", app: app)
    }
}
