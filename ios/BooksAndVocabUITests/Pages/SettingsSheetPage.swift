import XCTest

/// Page Object for the Settings sheet (opened from bookshelf toolbar).
struct SettingsSheetPage {
    let app: XCUIApplication

    /// Settings is presented in a sheet with a NavigationStack; the nav bar title is "設定".
    var navBar: XCUIElement {
        app.navigationBars.firstMatch
    }

    var closeButton: XCUIElement {
        app.buttons["完成"]
    }

    // MARK: - Actions

    @discardableResult
    func dismiss(file: StaticString = #filePath, line: UInt = UInt(#line)) -> BookshelfPage {
        closeButton.tapWhenReady(file: file, line: line)
        return BookshelfPage(app: app)
    }

    // MARK: - Assertions

    func assertIsPresented(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        // Confirm by the "完成" (Done) button in the sheet toolbar.
        closeButton.assertExists(file: file, line: line)
    }
}
