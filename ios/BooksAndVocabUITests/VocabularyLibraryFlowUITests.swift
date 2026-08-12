import XCTest

/// p11 acceptance flow: one UI World injects 40 rows with independent
/// learning/dictionary and unlearned/due/reviewed semantics. The test proves
/// the page is a query projection, not a set of unrelated chip side effects.
final class VocabularyLibraryFlowUITests: UITestCase {
    private static let notebookID = "ui-vocab-list-filter-rich-notebook"

    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 120
    }

    @MainActor
    func testRichWorldProjectsRoleReviewSearchAndCTAConsistently() throws {
        let app = launchIsolatedApp(
            fixtures: [.vocabularyLibraryFilterRich],
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
        XCTAssertTrue(app.waitForNavigationToSettle())
        let page = VocabularySearchPage(app: app)
        guard page.row(word: "knowledge-word-01").waitUntilExists(timeout: 10) else {
            captureStep("no-rich-vocabulary-rows", app: app)
            XCTFail("rich fixture 必須渲染 vocabulary rows")
            return
        }
        XCTAssertTrue(page.visibleCount.waitUntilExists(timeout: 5))
        captureStep("all-scope-40-rows", app: app)

        try step("dictionary-scope", app: app) {
            page.selectScope("dictionary", labelPrefix: "字典")
            XCTAssertTrue(page.row(word: "knowledge-word-04").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.row(word: "knowledge-word-06").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.row(word: "knowledge-word-01").waitUntilGone(timeout: 5))
            XCTAssertTrue(page.reviewStateMenu.waitUntilGone(timeout: 5))
        }

        try step("learning-scope-review-menu", app: app) {
            page.selectScope("learning", labelPrefix: "學習")
            XCTAssertTrue(page.reviewStateMenu.waitUntilExists(timeout: 5))
            page.openReviewStateMenu()
            XCTAssertTrue(page.reviewStateOption("unlearned", labelPrefix: "未學習").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.reviewStateOption("due", labelPrefix: "待複習").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.reviewStateOption("reviewed", labelPrefix: "已複習").waitUntilExists(timeout: 5))
            captureStep("learning-review-menu-open", app: app)
            page.selectReviewState("unlearned", labelPrefix: "未學習")
            XCTAssertTrue(page.row(word: "knowledge-word-01").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.row(word: "knowledge-word-02").waitUntilGone(timeout: 5))
        }

        try step("due-scope", app: app) {
            page.openReviewStateMenu()
            page.selectReviewState("due", labelPrefix: "待複習")
            XCTAssertTrue(page.row(word: "knowledge-word-02").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.row(word: "knowledge-word-01").waitUntilGone(timeout: 5))
            XCTAssertTrue(page.row(word: "knowledge-word-04").waitUntilGone(timeout: 5))
        }

        try step("search-within-projection", app: app) {
            page.openReviewStateMenu()
            page.selectReviewState("all", labelPrefix: "全部狀態")
            page.search("knowledge-word-39")
            XCTAssertTrue(page.row(word: "knowledge-word-39").waitUntilExists(timeout: 5))
            XCTAssertTrue(page.row(word: "knowledge-word-02").waitUntilGone(timeout: 5))
            page.clearSearch()
            XCTAssertTrue(page.row(word: "knowledge-word-02").waitUntilExists(timeout: 5))
        }

        captureStep("rich-projection-verified", app: app)
    }
}
