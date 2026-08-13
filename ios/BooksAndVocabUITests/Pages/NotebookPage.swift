import XCTest

/// Page Object for the Notebook List tab.
struct NotebookPage {
    let app: XCUIApplication

    // MARK: - Content

    var addButton: XCUIElement {
        exactlyOne("notebook.addButton", in: app.buttons)
    }

    /// Notebook card: `accessibilityIdentifier = "notebook.card.<notebookId>"`
    func notebookCard(id: String) -> XCUIElement {
        exactlyOne(
            "notebook.card.\(id)",
            in: app.descendants(matching: .any)
        )
    }

    var anyNotebookCard: XCUIElement {
        let matches = app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH[c] %@", "notebook.card."))
        XCTAssertEqual(matches.count, 1, "P1 notebook card selector must resolve exactly once")
        return matches.element
    }

    /// Today-review CTA pill in the action bar. The due / unlearned / combined
    /// branches share one identifier — only one renders at a time.
    var reviewCTAButton: XCUIElement {
        exactlyOne(
            "notebook.reviewCTA",
            in: app.descendants(matching: .any)
        )
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

    private func exactlyOne(_ identifier: String, in query: XCUIElementQuery) -> XCUIElement {
        let matches = query.matching(identifier: identifier)
        XCTAssertEqual(matches.count, 1, "P1 selector must resolve exactly once: \(identifier)")
        return matches.element
    }
}
