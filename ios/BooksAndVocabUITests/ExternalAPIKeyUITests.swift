import XCTest

final class ExternalAPIKeyUITests: UITestCase {
    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 240
    }

    @MainActor
    func testFreeAccountDoesNotExposeAPIKeyManagement() throws {
        let app = launchIsolatedApp(
            fixtures: [.authSignedIn],
            perfLog: "external-api-key-free"
        )
        let settings = AppPage(app: app).goToBookshelf().tapSettings()
        settings.assertIsPresented()
        settings.openAccountDetail()

        XCTAssertTrue(settings.accountScrollView.waitUntilExists(timeout: 10))
        XCTAssertEqual(
            app.buttons.matching(identifier: "settings.account.apiKeyManagement").count,
            0,
            "Free account must not expose the API key management entry point"
        )
    }

    @MainActor
    func testProAccountOpensAPIKeyManagementPage() throws {
        let app = launchIsolatedApp(
            fixtures: [.authSignedIn, .entitlementsProAccess],
            perfLog: "external-api-key-pro"
        )
        let settings = AppPage(app: app).goToBookshelf().tapSettings()
        settings.assertIsPresented()
        settings.openAccountDetail()

        let apiKeys = settings.openAPIKeyManagement()
        apiKeys.assertIsPresented()

        // The management surface is reachable without assuming a live API-key
        // response; a fixture/network failure may render either empty or error,
        // but must not remove the Pro-gated page itself.
        XCTAssertTrue(
            apiKeys.createButton.waitUntilExists(timeout: 10)
                || apiKeys.error.waitUntilExists(timeout: 10),
            "API key page must render either its create action or a retryable load error"
        )
    }
}
