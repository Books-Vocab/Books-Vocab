import XCTest

/// Page object for the notebook-scoped settings route.
struct NotebookSettingsPage {
    let app: XCUIApplication

    var header: XCUIElement { element("notebook.settings.header") }
    var reviewSection: XCUIElement { element("notebook.settings.reviewSection") }
    var reviewMode: XCUIElement { element("notebook.settings.reviewMode") }
    var layoutSection: XCUIElement { element("notebook.settings.layoutSection") }
    var layoutEditor: XCUIElement {
        let button = app.buttons["notebook.settings.cardLayoutEditor"]
        if button.exists && button.isHittable { return button }
        return app.staticTexts["編輯複習卡片"]
    }
    var title: XCUIElement { app.navigationBars["單字本設定"] }

    @discardableResult
    func goBack(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        XCTAssertTrue(
            title.waitUntilExists(timeout: 5),
            "Notebook settings title must exist before going back",
            file: file,
            line: line
        )
        app.navigationBars.buttons.element(boundBy: 0).tapWhenReady(file: file, line: line)
        return self
    }

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(identifier: identifier)
            .firstMatch
    }
}
