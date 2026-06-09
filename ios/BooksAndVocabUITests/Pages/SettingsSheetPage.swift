import XCTest

/// Page Object for the Settings sheet (opened from bookshelf toolbar).
struct SettingsSheetPage {
    let app: XCUIApplication

    // MARK: - Navigation

    var navBar: XCUIElement {
        app.navigationBars["settings.navBar"]
    }

    var closeButton: XCUIElement {
        navBar.buttons.firstMatch
    }

    // MARK: - Content

    var accountSection: XCUIElement {
        app.staticTexts["settings.section.account"]
    }

    var reviewSection: XCUIElement {
        app.staticTexts["settings.section.review"]
    }

    // MARK: - Actions

    @discardableResult
    func dismiss(file: StaticString = #filePath, line: UInt = #line) -> BookshelfPage {
        closeButton.tapWhenReady(file: file, line: line)
        return BookshelfPage(app: app)
    }

    // MARK: - Assertions

    func assertIsPresented(file: StaticString = #filePath, line: UInt = #line) {
        navBar.assertExists(file: file, line: line)
    }
}
