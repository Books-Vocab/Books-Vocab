import XCTest

final class DictionaryLookupFlowUITests: UITestCase {
    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 120
    }

    @MainActor
    func testDictionaryResultShowsCanonicalSensesProvenanceAndMaterialization() throws {
        let (app, page) = try openDictionarySheet(perfLog: "dictionary-result")
        page.search("engraved")

        page.assertCanonicalState("result")
        XCTAssertTrue(page.sense(id: "sense-1").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.sense(id: "sense-2").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.example(id: "example-1").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.example(id: "example-2").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.provenance.waitUntilLabelContains("canonical dictionary fixture", timeout: 5))
        XCTAssertTrue(page.materialization(status: "ready").waitUntilValueContains(
            "sense-1|example-1|dictionary.lookup.result|marketing_demo|",
            timeout: 5
        ))
        page.tapSense(id: "sense-1")
        page.tapExample(id: "example-1")
        page.tapMaterialize()
        TodayReviewPage(app: app).assertLink(id: "fixture-dictionary-card")
        captureStep("canonical-result", app: app)
    }

    @MainActor
    func testDictionaryLoadingAndEmptySelectorsAreLive() throws {
        let (app, page) = try openDictionarySheet(perfLog: "dictionary-loading-empty")
        page.search("loading")
        page.assertCanonicalState("loading")
        captureStep("loading", app: app)
        page.assertCanonicalState("result")

        // A fresh sheet keeps the query transition deterministic and avoids
        // relying on XCTest's text-selection behavior across iOS versions.
        let (emptyApp, emptyPage) = try openDictionarySheet(perfLog: "dictionary-empty")
        emptyPage.search("empty")
        XCTAssertTrue(emptyPage.emptyState.waitUntilExists(timeout: 10))
        captureStep("empty", app: emptyApp)
    }

    @MainActor
    func testDictionaryPartialRetryAndRetryingSelectorsAreLive() throws {
        let (app, page) = try openDictionarySheet(perfLog: "dictionary-partial-retry")
        page.search("partial")
        page.assertCanonicalState("partial")
        page.assertRetryButton()
        captureStep("partial", app: app)

        page.retryButton.tap()
        page.assertCanonicalState("retrying")
        captureStep("retrying", app: app)
        page.assertCanonicalState("result")
    }

    @MainActor
    func testDictionaryOfflineAndErrorSelectorsExposeRetry() throws {
        let (offlineApp, offlinePage) = try openDictionarySheet(perfLog: "dictionary-offline")
        offlinePage.search("offline")
        offlinePage.assertCanonicalState("offline")
        offlinePage.assertRetryButton()
        captureStep("offline", app: offlineApp)

        let (errorApp, errorPage) = try openDictionarySheet(perfLog: "dictionary-error")
        errorPage.search("error")
        errorPage.assertCanonicalState("error")
        errorPage.assertRetryButton()
        captureStep("error", app: errorApp)
    }

    @MainActor
    private func openDictionarySheet(perfLog: String) throws -> (XCUIApplication, DictionaryLookupPage) {
        let app = launchIsolatedApp(
            fixtures: [.dictionaryP1Rich, .notebookReviewDeck],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"],
            perfLog: perfLog
        )
        captureStep("launch", app: app)

        let notebook = AppPage(app: app).goToNotebooks()
        guard notebook.notebookCard(id: "ui-review-notebook").waitUntilExists(timeout: 10) else {
            captureStep("no-notebook", app: app)
            XCTFail("notebook review fixture did not render")
            throw NSError(domain: "DictionaryLookupFlowUITests", code: 1)
        }
        guard notebook.reviewCTAButton.waitUntilExists(timeout: 10) else {
            captureStep("no-review-cta", app: app)
            XCTFail("notebook review fixture did not expose review CTA")
            throw NSError(domain: "DictionaryLookupFlowUITests", code: 2)
        }

        let review = notebook.startReview()
        guard review.progressLabel.waitUntilExists(timeout: 10) else {
            captureStep("no-review", app: app)
            XCTFail("review session did not mount")
            throw NSError(domain: "DictionaryLookupFlowUITests", code: 3)
        }
        review.flipCard()
        guard review.addLinkButton.waitUntilExists(timeout: 10) else {
            captureStep("no-add-link", app: app)
            XCTFail("review card did not expose add-link action")
            throw NSError(domain: "DictionaryLookupFlowUITests", code: 4)
        }
        review.addLinkButton.tapWhenReady()

        let page = DictionaryLookupPage(app: app).waitForSheet()
        return (app, page)
    }
}
