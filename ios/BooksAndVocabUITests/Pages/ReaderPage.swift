import XCTest

/// Page Object for the Reader (book reading) scene.
struct ReaderPage {
    let app: XCUIApplication

    // MARK: - Chrome

    var backButton: XCUIElement {
        app.navigationBars.buttons.firstMatch
    }

    var translationPanel: XCUIElement {
        app.otherElements["reader.translationPanel"]
    }

    var settingsPanel: XCUIElement {
        app.otherElements["reader.settingsPanel"]
    }

    // MARK: - Actions

    @discardableResult
    func goBack(file: StaticString = #filePath, line: UInt = #line) -> BookshelfPage {
        backButton.tapWhenReady(file: file, line: line)
        return BookshelfPage(app: app)
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = #line) {
        backButton.assertExists(timeout: 5, file: file, line: line)
    }
}
