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

        XCTAssertTrue(page.result.waitUntilExists(timeout: 10))
        XCTAssertTrue(page.sense(id: "sense-1").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.sense(id: "sense-2").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.example(id: "example-1").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.example(id: "example-2").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.provenance.waitUntilLabelContains("canonical dictionary fixture", timeout: 5))
        XCTAssertTrue(page.materialization(status: "ready").waitUntilValueEquals(
            "sense-1|example-1|dictionary.lookup.result",
            timeout: 5
        ))
        captureStep("canonical-result", app: app)
    }

    @MainActor
    func testDictionaryLoadingAndEmptySelectorsAreLive() throws {
        let (app, page) = try openDictionarySheet(perfLog: "dictionary-loading-empty")
        page.search("loading")
        XCTAssertTrue(page.loadingState.waitUntilExists(timeout: 5))
        captureStep("loading", app: app)
        XCTAssertTrue(page.result.waitUntilExists(timeout: 10))

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
        XCTAssertTrue(page.partialState.waitUntilExists(timeout: 10))
        XCTAssertTrue(page.retryButton.waitUntilHittable(timeout: 5))
        captureStep("partial", app: app)

        page.retryButton.tap()
        XCTAssertTrue(page.retryingState.waitUntilExists(timeout: 5))
        captureStep("retrying", app: app)
        XCTAssertTrue(page.result.waitUntilExists(timeout: 10))
    }

    @MainActor
    func testDictionaryOfflineAndErrorSelectorsExposeRetry() throws {
        let (offlineApp, offlinePage) = try openDictionarySheet(perfLog: "dictionary-offline")
        offlinePage.search("offline")
        XCTAssertTrue(offlinePage.offlineState.waitUntilExists(timeout: 10))
        XCTAssertTrue(offlinePage.retryButton.waitUntilHittable(timeout: 5))
        captureStep("offline", app: offlineApp)

        let (errorApp, errorPage) = try openDictionarySheet(perfLog: "dictionary-error")
        errorPage.search("error")
        XCTAssertTrue(errorPage.errorState.waitUntilExists(timeout: 10))
        XCTAssertTrue(errorPage.retryButton.waitUntilHittable(timeout: 5))
        captureStep("error", app: errorApp)
    }

    @MainActor
    private func openDictionarySheet(perfLog: String) throws -> (XCUIApplication, DictionaryLookupPage) {
        let app = launchIsolatedApp(
            fixtures: [.notebookReviewDeck],
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
