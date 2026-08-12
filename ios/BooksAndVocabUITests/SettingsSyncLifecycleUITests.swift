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
        settings.syncSummaryButton.tapWhenReady()
        XCTAssertTrue(
            settings.syncLifecycleStatus.waitForExistence(timeout: 5),
            "first deterministic fixture round must render terminal error"
        )
        XCTAssertEqual(settings.syncLifecycleStatus.label, "同步失敗")
        XCTAssertTrue(settings.retrySyncButton.exists)
        XCTAssertTrue(settings.syncLifecycleMessage.exists)
        captureStep("terminal-error-real-service", app: app)

        settings.retrySyncButton.tapWhenReady()
        XCTAssertTrue(
            settings.syncLifecycleStatus.waitForExistence(timeout: 5),
            "retry must render terminal success"
        )
        XCTAssertEqual(settings.syncLifecycleStatus.label, "同步完成")
        XCTAssertFalse(settings.retrySyncButton.exists)
        XCTAssertTrue(settings.dismissSyncStatusButton.exists)
        captureStep("retry-real-service", app: app)

        attachText(
            "lifecycle=terminalError -> retry -> terminalSuccess\nservice=KGService.backgroundSync transport=FixtureDatasetStore\ndata=partial SwiftData residual -> complete SwiftData read\nselectors=settings.syncLifecycle.status,settings.syncLifecycle.message,settings.syncLifecycle.retryButton,settings.syncLifecycle.dismissButton",
            named: "Settings Sync Lifecycle Evidence"
        )

        settings.dismissSyncStatusButton.tapWhenReady()
        XCTAssertFalse(settings.syncLifecycle.exists)
    }
}
