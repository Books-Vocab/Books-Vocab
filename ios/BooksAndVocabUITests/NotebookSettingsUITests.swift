import XCTest

/// Notebook detail → pushed notebook settings route.
final class NotebookSettingsUITests: UITestCase {
    private static let notebookCardID = "ui-review-notebook"

    override func setUpWithError() throws {
        try super.setUpWithError()
        executionTimeAllowance = 120
    }

    @MainActor
    func testNotebookDetailPushesScopedSettingsAndReusesLayoutEditor() throws {
        let app = launchIsolatedApp(
            fixtures: [.notebookReviewDeck],
            extraEnvironment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"]
        )
        captureStep("launch", app: app)

        let notebooks = AppPage(app: app).goToNotebooks()
        guard notebooks.waitForNotebookCard(id: Self.notebookCardID, timeout: 10) else {
            captureStep("no-notebook-card", app: app)
            XCTFail("notebook.reviewDeck fixture 必須提供單字本卡片")
            return
        }
        notebooks.notebookCard(id: Self.notebookCardID).tapWhenReady()

        let settings = NotebookSettingsPage(app: app)
        guard app.buttons["notebook.settingsButton"].waitUntilHittable(timeout: 10) else {
            captureStep("no-settings-button", app: app)
            XCTFail("單字本 detail toolbar 必須提供設定入口")
            return
        }
        app.buttons["notebook.settingsButton"].tapWhenReady()

        settings.title.assertExists(timeout: 10)
        settings.header.assertExists(timeout: 10)
        XCTAssertTrue(settings.header.label.contains("目前單字本"))
        settings.reviewSection.assertExists()
        settings.layoutSection.assertExists()
        XCTAssertEqual(
            app.descendants(matching: .any)
                .matching(NSPredicate(format: "identifier CONTAINS[c] %@", "WordDetail"))
                .count,
            0,
            "WordDetailSheet 不應承載 notebook review settings"
        )
        captureStep("notebook-settings", app: app)

        settings.layoutEditor.tapWhenReady()
        let editor = ReviewCardLayoutEditorPage(app: app)
        XCTAssertTrue(editor.waitUntilVisible(timeout: 10))
        editor.previewCard.assertExists()
        captureStep("scoped-layout-editor", app: app)

        editor.doneButton.tapWhenReady()
        settings.title.assertExists(timeout: 5)
        settings.goBack()
        XCTAssertTrue(
            app.buttons["notebook.settingsButton"].waitUntilExists(timeout: 5),
            "返回單字本 detail 後設定入口仍應存在"
        )
        captureStep("returned-to-notebook-detail", app: app)
    }
}
