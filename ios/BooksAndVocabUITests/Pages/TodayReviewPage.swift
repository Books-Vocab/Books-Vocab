import XCTest

/// Page Object for the Today Review (flashcard) scene.
struct TodayReviewPage {
    let app: XCUIApplication

    // MARK: - Chrome

    var backButton: XCUIElement {
        app.navigationBars.buttons.firstMatch
    }

    var cardFront: XCUIElement {
        app.otherElements["todayReview.card.front"]
    }

    var cardBack: XCUIElement {
        app.otherElements["todayReview.card.back"]
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
