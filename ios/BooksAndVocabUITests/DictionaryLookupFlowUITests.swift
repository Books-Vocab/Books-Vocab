import CryptoKit
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
        let materialization = page.assertMaterialization(status: "ready")
        let datasetSHA256 = try DictionaryFixtureManifest.datasetSHA256()
        XCTAssertTrue(materialization.waitUntilValueContains(
            "sense-1|example-1|dictionary.lookup.result|marketing_demo|\(datasetSHA256)|catalog_reader_epub|",
            timeout: 5
        ), "materialization AX value did not contain the typed provenance prefix: \(String(describing: materialization.value))")
        XCTAssertTrue(materialization.waitUntilValueContains(
            "|1690|4cfe357ba9c217fbfbe1af6b2831c69e0d476041267c99fae81ea5ba1967c3de",
            timeout: 5
        ), "materialization AX value did not contain the asset integrity suffix: \(String(describing: materialization.value))")
        captureStep("success", app: app)
        page.tapSense(id: "sense-1")
        page.tapExample(id: "example-1")
        page.tapMaterialize()
        TodayReviewPage(app: app).assertLink(id: "fixture-dictionary-card")
        captureStep("canonical-result", app: app)
    }

    @MainActor
    func testP2DictionarySensesUsesIndependentTypedSurfaceSelector() throws {
        let (app, page) = try openDictionarySheet(
            fixture: .dictionaryP2Senses,
            perfLog: "dictionary-p2-senses"
        )
        page.search("engraved")

        page.assertCanonicalState("result")
        XCTAssertTrue(page.sense(id: "sense-1").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.sense(id: "sense-2").waitUntilExists(timeout: 5))
        XCTAssertTrue(page.example(id: "example-2").waitUntilExists(timeout: 5))
        captureStep("detail", app: app)
        page.tapSense(id: "sense-2")
        captureStep("select-sense", app: app)
        page.tapExample(id: "example-2")
        page.tapMaterialize()
        TodayReviewPage(app: app).assertLink(id: "fixture-dictionary-card")
        captureStep("materialize", app: app)
    }

    @MainActor
    func testDictionaryLoadingAndEmptySelectorsAreLive() throws {
        let (app, page) = try openDictionarySheet(
            perfLog: "dictionary-loading-empty",
            extraArgs: ["-dictionaryLoadingGate"]
        )
        page.enterQuery("loading")
        page.assertCanonicalState("idle")
        captureStep("idle", app: app)
        page.submitQuery()
        page.assertCanonicalState("loading")
        captureStep("loading", app: app)
        page.releaseLoading()
        page.assertCanonicalState("result")

        // A fresh sheet keeps the query transition deterministic and avoids
        // relying on XCTest's text-selection behavior across iOS versions.
        let (emptyApp, emptyPage) = try openDictionarySheet(perfLog: "dictionary-empty")
        emptyPage.search("empty")
        emptyPage.assertEmptyState()
        captureStep("empty", app: emptyApp)
    }

    @MainActor
    func testDictionaryPartialRetryAndRetryingSelectorsAreLive() throws {
        let (app, page) = try openDictionarySheet(
            perfLog: "dictionary-partial-retry",
            extraArgs: ["-dictionaryRetryGate"]
        )
        page.search("partial")
        page.assertCanonicalState("partial")
        page.assertRetryButton()
        captureStep("partial-result", app: app)

        page.retryButton.tap()
        page.assertCanonicalState("retrying")
        captureStep("retry", app: app)
        captureStep("retrying", app: app)
        page.releaseRetryRequest()
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
    func testP2DictionaryMissingExampleCounterexampleIsVisible() throws {
        let (app, page) = try openDictionarySheet(
            fixture: .dictionaryP2Senses,
            perfLog: "dictionary-p2-missing-example"
        )
        page.search("missing-example")
        page.assertCanonicalState("result")
        page.tapSense(id: "sense-2")
        XCTAssertFalse(page.example(id: "example-2").exists)
        captureStep("missing-example-counterexample", app: app)
    }

    @MainActor
    func testP2DictionaryMaterializationErrorPreservesSelection() throws {
        let (app, page) = try openDictionarySheet(
            fixture: .dictionaryP2Senses,
            perfLog: "dictionary-p2-materialize-error"
        )
        page.search("materialize-error")
        page.assertCanonicalState("result")
        page.tapSense(id: "sense-2")
        page.tapExample(id: "example-2")
        page.tapMaterialize()
        XCTAssertTrue(page.materializationFailure.waitUntilExists(timeout: 10))
        XCTAssertTrue(page.materializationFailure.value as? String == "dictionary.p2.materialize-error")
        captureStep("materialize-error-counterexample", app: app)
    }

    @MainActor
    private func openDictionarySheet(
        fixture: UITestFixture = .dictionaryP1Rich,
        perfLog: String,
        extraArgs: [String] = []
    ) throws -> (XCUIApplication, DictionaryLookupPage) {
        let app = launchIsolatedApp(
            extraArgs: extraArgs,
            fixtures: [.authSignedIn, fixture, .notebookReviewDeck],
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
        review.assertAddLinkButtonIsUnique()
        review.addLinkButton.tapWhenReady()

        let page = DictionaryLookupPage(app: app).waitForSheet()
        return (app, page)
    }
}

private enum DictionaryFixtureManifest {
    static func datasetSHA256() throws -> String {
        let environment = ProcessInfo.processInfo.environment
        let data: Data
        if let deflateB64 = environment["KG_FIXTURE_DATASET_DEFLATE_B64"], !deflateB64.isEmpty {
            guard let compressed = Data(base64Encoded: deflateB64) else {
                throw NSError(domain: "DictionaryFixtureManifest", code: 1)
            }
            data = try (compressed as NSData).decompressed(using: .zlib) as Data
        } else if let base64 = environment["KG_FIXTURE_DATASET_B64"], !base64.isEmpty {
            guard let decoded = Data(base64Encoded: base64) else {
                throw NSError(domain: "DictionaryFixtureManifest", code: 2)
            }
            data = decoded
        } else {
            throw NSError(domain: "DictionaryFixtureManifest", code: 3)
        }
        return SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
