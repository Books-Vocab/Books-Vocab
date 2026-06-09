import XCTest

/// Page Object for the Knowledge Graph scene.
struct KnowledgeGraphPage {
    let app: XCUIApplication

    // MARK: - Chrome

    var backButton: XCUIElement {
        app.navigationBars.buttons.firstMatch
    }

    var webView: XCUIElement {
        app.webViews.firstMatch
    }

    // MARK: - Actions

    @discardableResult
    func goBack(file: StaticString = #filePath, line: UInt = UInt(#line)) -> NotebookPage {
        backButton.tapWhenReady(file: file, line: line)
        return NotebookPage(app: app)
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        backButton.assertExists(timeout: 5, file: file, line: line)
    }
}
