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

        settings.openSyncSummary()
        settings.assertTerminalFeedback(
            status: "同步失敗",
            expectedEvidence: "schema=settings.sync.evidence.v1;lifecycle=terminalError;attempt=1;dataOutcome=partial;residualCount=1;residualWords=residual;readBackCount=0;readBackWords=-;dictionaryEvents=round=1,path=/api/dictionary-cards,status=429|round=1,path=/api/dictionary-cards,status=429|round=1,path=/api/dictionary-cards,status=429;perfMarks=settings.sync.lifecycle.started{attempt=1}|settings.sync.lifecycle.saveResult{attempt=1 result=success}|settings.sync.lifecycle.serviceResult{attempt=1 result=failed}|settings.sync.lifecycle.terminal{attempt=1 state=terminalError data=partial}"
        )
        XCTAssertTrue(settings.retrySyncButton.exists)
        XCTAssertTrue(settings.syncLifecycleMessage.exists)
        captureStep("terminal-error-real-service", app: app)

        XCTAssertTrue(settings.retrySyncButton.exists)
        settings.retrySyncButton.tapWhenReady()
        settings.assertTerminalFeedback(
            status: "同步完成",
            expectedEvidence: "schema=settings.sync.evidence.v1;lifecycle=terminalSuccess;attempt=2;dataOutcome=complete;residualCount=1;residualWords=residual;readBackCount=2;readBackWords=complete,residual;dictionaryEvents=round=1,path=/api/dictionary-cards,status=429|round=1,path=/api/dictionary-cards,status=429|round=1,path=/api/dictionary-cards,status=429|round=2,path=/api/dictionary-cards,status=200;perfMarks=settings.sync.lifecycle.started{attempt=2}|settings.sync.lifecycle.saveResult{attempt=2 result=success}|settings.sync.lifecycle.serviceResult{attempt=2 result=completed}|settings.sync.lifecycle.terminal{attempt=2 state=terminalSuccess data=complete}"
        )
        XCTAssertFalse(settings.retrySyncButton.exists)
        XCTAssertTrue(settings.dismissSyncStatusButton.exists)
        captureStep("retry-real-service", app: app)

        XCTAssertTrue(settings.dismissSyncStatusButton.exists)
        settings.dismissSyncStatusButton.tapWhenReady()
        XCTAssertEqual(settings.syncLifecycleQuery.count, 0)
    }
}
