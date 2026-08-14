import XCTest

/// P11 acceptance flow: the report baseline injects 644 role-pure learning
/// rows. Its review buckets are 14/503/127 and its CTA is 517. The separate
/// `role.mixed` fixture is a small counterexample, never the baseline.
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

    func testP11LaunchSelectorsAreBoundToCanonicalWorlds() {
        XCTAssertEqual(
            UITestFixture.vocabularyLibraryP11ReviewMix.launchArgument,
            "-seedFixture:vocabulary:p11.644.reviewMix"
        )
        XCTAssertEqual(
            UITestFixture.vocabularyLibraryP11MixedRoleCounterexample.launchArgument,
            "-seedFixture:vocabulary:role.mixed"
        )
        XCTAssertNotEqual(
            UITestFixture.vocabularyLibraryP11ReviewMix.launchArgument,
            UITestFixture.vocabularyLibraryFilterRich.launchArgument,
            "P11 must never silently run the legacy 40-row fixture"
        )
    }

    @MainActor
    func testRichWorldProjectsRoleReviewSearchAndCTAConsistently() throws {
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
        captureStep("all-scope-644-rows", app: app)
        XCTAssertTrue(page.visibleCount.label.contains("644"), "all scope must show 644 visible rows")
        XCTAssertTrue(page.scopeOption("dictionary", labelPrefix: "字典").label.contains("0"))
        XCTAssertTrue(page.scopeOption("learning", labelPrefix: "學習").label.contains("644"))
        XCTAssertTrue(page.reviewCTA.waitUntilExists(timeout: 5), "report baseline CTA must be visible")
        XCTAssertTrue(page.reviewCTA.label.contains("517"), "report baseline CTA must be exactly 517")
        XCTAssertTrue(page.sortMenu.waitUntilExists(timeout: 5), "sort control must remain a separate semantic control")
        XCTAssertTrue(page.reviewStateOption("unlearned", labelPrefix: "未學習").label.contains("14"))
        XCTAssertTrue(page.reviewStateOption("due", labelPrefix: "待複習").label.contains("503"))
        XCTAssertTrue(page.reviewStateOption("reviewed", labelPrefix: "已複習").label.contains("127"))
        XCTAssertTrue(page.reviewCTA.isHittable, "CTA must remain hittable at accessibility3")
        XCTAssertTrue(page.sortMenu.isHittable, "sort must remain hittable at accessibility3")
        captureStep("dynamic-type", app: app)
        captureStep("cta", app: app)

        try step("dictionary-scope", app: app) {
            page.selectScope("dictionary", labelPrefix: "字典")
            XCTAssertTrue(page.visibleCount.label.contains("0"), "baseline dictionary scope must be empty")
            XCTAssertTrue(page.reviewStateControls.waitUntilGone(timeout: 5))
            XCTAssertTrue(page.reviewCTA.waitUntilGone(timeout: 5), "dictionary scope must not expose a review CTA")
            XCTAssertTrue(page.sortMenu.label.contains("字母序"), "dictionary scope must canonicalize sort to alphabetical")
        }

        try step("learning-review", app: app) {
            page.selectScope("learning", labelPrefix: "學習")
            XCTAssertTrue(page.reviewStateControls.waitUntilExists(timeout: 5))
            XCTAssertTrue(page.visibleCount.label.contains("644"), "learning scope must show exactly 644 learning rows")
            XCTAssertTrue(page.reviewStateOption("unlearned", labelPrefix: "未學習").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.reviewStateOption("due", labelPrefix: "待複習").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.reviewStateOption("reviewed", labelPrefix: "已複習").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.reviewStateOption("unlearned", labelPrefix: "未學習").label.contains("14"))
            XCTAssertTrue(page.reviewStateOption("due", labelPrefix: "待複習").label.contains("503"))
            XCTAssertTrue(page.reviewStateOption("reviewed", labelPrefix: "已複習").label.contains("127"))
            captureStep("learning-review-menu-open", app: app)
            page.selectReviewState("unlearned", labelPrefix: "未學習")
            XCTAssertTrue(page.visibleCount.label.contains("14"))
            XCTAssertTrue(page.row(word: "p11-review-word-001").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.row(word: "p11-review-word-015").waitUntilGone(timeout: 5))
            page.selectReviewState("due", labelPrefix: "待複習")
            XCTAssertTrue(page.visibleCount.label.contains("517"), "multi-select must union 14 unlearned and 503 due rows")
            XCTAssertTrue(page.row(word: "p11-review-word-001").waitUntilExists(timeout: 5))
            page.search("p11-review-word-015")
            XCTAssertTrue(page.visibleCount.label.contains("1"), "union must include a due row")
            XCTAssertTrue(page.row(word: "p11-review-word-015").waitUntilExists(timeout: 5))
            page.clearSearch()
            XCTAssertTrue(page.visibleCount.label.contains("517"))
        }

        try step("reviewed-scope", app: app) {
            page.clearReviewStates()
            page.selectReviewState("reviewed", labelPrefix: "已複習")
            XCTAssertTrue(page.visibleCount.label.contains("127"))
            page.search("p11-review-word-518")
            XCTAssertTrue(page.visibleCount.label.contains("1"), "reviewed facet must project a reviewed row")
            XCTAssertTrue(page.row(word: "p11-review-word-518").waitUntilExists(timeout: 5))
            page.clearSearch()
            XCTAssertTrue(page.visibleCount.label.contains("127"))
        }

        try step("search-within-projection", app: app) {
            page.clearReviewStates()
            page.search("p11-review-word-001")
            XCTAssertTrue(page.visibleCount.label.contains("1"), "search visible count must be independent from facet counts")
            XCTAssertTrue(page.row(word: "p11-review-word-001").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.row(word: "p11-review-word-015").waitUntilGone(timeout: 5))
            XCTAssertTrue(page.reviewStateOption("unlearned", labelPrefix: "未學習").label.contains("14"))
            XCTAssertTrue(page.reviewStateOption("due", labelPrefix: "待複習").label.contains("503"))
            XCTAssertTrue(page.reviewStateOption("reviewed", labelPrefix: "已複習").label.contains("127"))
            page.clearSearch()
            XCTAssertTrue(page.visibleCount.label.contains("644"))
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

        // The rich fixture has 644 rows and AX3 intentionally exercises a
        // large accessibility tree. Terminate it before launching the small
        // counterexample app so two XCUIApplication processes never compete
        // for the simulator accessibility/runtime channel.
        app.terminate()

        let mixedApp = launchIsolatedApp(
            extraArgs: [
                "-UIPreferredContentSizeCategoryName",
                "UICTContentSizeCategoryAccessibility3",
            ],
            fixtures: [.vocabularyLibraryP11MixedRoleCounterexample],
            extraEnvironment: [
                "KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"
            ],
            perfLog: "vocabulary-filter-rich-mixed-role"
        )
        try step("mixed-role", app: mixedApp) {
            let mixedShell = AppPage(app: mixedApp)
            let mixedNotebooks = mixedShell.goToNotebooks()
            let mixedNotebookID = "ui-p11-role-mixed-notebook"
            XCTAssertTrue(mixedNotebooks.notebookCard(id: mixedNotebookID).waitUntilExists(timeout: 10))
            mixedNotebooks.notebookCard(id: mixedNotebookID).tapWhenReady()
            XCTAssertTrue(mixedApp.waitForNavigationToSettle())
            let mixedPage = VocabularySearchPage(app: mixedApp)
            XCTAssertTrue(mixedPage.visibleCount.waitUntilExists(timeout: 10))
            XCTAssertTrue(mixedPage.visibleCount.label.contains("4"))
            XCTAssertTrue(mixedPage.scopeOption("dictionary", labelPrefix: "字典").label.contains("2"))
            XCTAssertTrue(mixedPage.scopeOption("learning", labelPrefix: "學習").label.contains("2"))
        }

    }
}
