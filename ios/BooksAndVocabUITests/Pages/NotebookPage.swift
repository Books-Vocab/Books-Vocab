import XCTest

/// Page Object for the Notebook List tab.
struct NotebookPage {
    let app: XCUIApplication

    // MARK: - Content

    var addButton: XCUIElement {
        app.buttons["notebook.addButton"]
    }

    /// Notebook card: `accessibilityIdentifier = "notebook.card.<notebookId>"`
    func notebookCard(id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: "notebook.card.\(id)").firstMatch
    }

    var anyNotebookCard: XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH[c] %@", "notebook.card."))
            .firstMatch
    }

    /// Today-review CTA pill in the action bar. The due / unlearned / combined
    /// branches share one identifier — only one renders at a time.
    var reviewCTAButton: XCUIElement {
        app.descendants(matching: .any)
            .matching(identifier: "notebook.reviewCTA")
            .firstMatch
    }

    // MARK: - Actions

    @discardableResult
    func tapAdd(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        addButton.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func startReview(file: StaticString = #filePath, line: UInt = UInt(#line)) -> TodayReviewPage {
        reviewCTAButton.tapWhenReady(file: file, line: line)
        return TodayReviewPage(app: app)
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        addButton.assertExists(file: file, line: line)
    }
}
