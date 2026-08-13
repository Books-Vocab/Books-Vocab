import XCTest

final class SettingsSyncLifecycleUITests: UITestCase {
    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 120
    }

    @MainActor
    func testSettingsSyncTerminalErrorRetriesToSuccess() throws {
        let app = launchIsolatedApp(
            fixtures: [
                .authSignedIn,
                .settingsCleanPreferences,
                .entitlementsProAccess,
                .settingsSyncTerminalErrorRetrySuccess
            ],
            perfLog: "settings-sync-lifecycle"
        )
        let settings = AppPage(app: app).goToBookshelf().tapSettings()
        settings.assertIsPresented()

        settings.syncSummaryButton.scrollIntoView()
        XCTAssertEqual(settings.app.buttons.matching(identifier: "settings.syncSummary").count, 1)
        XCTAssertGreaterThan(settings.syncSummaryButton.frame.width, 0)
        XCTAssertGreaterThan(settings.syncSummaryButton.frame.height, 0)
        settings.syncSummaryButton.tapWhenReady()
        settings.assertTerminalFeedback(
            status: "同步失敗",
            markerContains: [
                "schema=settings.sync.evidence.v1",
                "lifecycle=terminalError",
                "attempt=1",
                "dataOutcome=partial",
                "residualWords=residual",
                "readBackWords=-",
                "round=1,path=/api/dictionary-cards,status=429",
                "settings.sync.lifecycle.serviceResult"
            ]
        )
        XCTAssertEqual(settings.retrySyncButton.count, 1)
        XCTAssertEqual(settings.syncLifecycleMessage.count, 1)
        captureStep("terminal-error-real-service", app: app)

        settings.retrySyncButton.tapWhenReady()
        settings.assertTerminalFeedback(
            status: "同步完成",
            markerContains: [
                "schema=settings.sync.evidence.v1",
                "lifecycle=terminalSuccess",
                "attempt=2",
                "dataOutcome=complete",
                "residualWords=residual",
                "readBackWords=complete,residual",
                "round=2,path=/api/vocab,status=200",
                "settings.sync.lifecycle.serviceResult"
            ]
        )
        XCTAssertEqual(settings.retrySyncButton.count, 0)
        XCTAssertEqual(settings.dismissSyncStatusButton.count, 1)
        captureStep("retry-real-service", app: app)

        settings.dismissSyncStatusButton.tapWhenReady()
        XCTAssertEqual(settings.syncLifecycleQuery.count, 0)
    }
}
