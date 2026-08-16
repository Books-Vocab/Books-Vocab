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

    /// Wait for the fixture card's AX projection without asserting against an
    /// expected zero-match snapshot. Each poll re-resolves the query and keeps
    /// the positive state exact-one before callers use the action accessor.
    @discardableResult
    func waitForNotebookCard(id: String, timeout: TimeInterval = 8) -> Bool {
        let query = app.descendants(matching: .any)
            .matching(identifier: "notebook.card.\(id)")
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            let matches = query.allElementsBoundByIndex
            if matches.count == 1, matches[0].exists { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        let matches = query.allElementsBoundByIndex
        return matches.count == 1 && matches[0].exists
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
