import XCTest

/// Page Object for the Bookshelf tab.
struct BookshelfPage {
    let app: XCUIApplication

    // MARK: - Toolbar / Chrome

    var importButton: XCUIElement {
        app.buttons["bookshelf.importButton"]
    }

    var settingsButton: XCUIElement {
        app.buttons["bookshelf.settingsButton"]
    }

    var refreshButton: XCUIElement {
        app.buttons["bookshelf.refreshButton"]
    }

    // MARK: - Content

    var emptyStateTitle: XCUIElement {
        app.staticTexts["bookshelf.emptyState.title"]
    }

    var emptyStateImportButton: XCUIElement {
        app.buttons["bookshelf.emptyState.importButton"]
    }

    // MARK: - Book Grid

    /// Returns the first book card in the grid. Books are identified by
    /// `accessibilityIdentifier = "book.card.<bookId>"`.
    func bookCard(id: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: "book.card.\(id)").firstMatch
    }

    /// Returns any book card (useful when exact IDs are unknown).
    var anyBookCard: XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH[c] %@", "book.card."))
            .firstMatch
    }

    // MARK: - Actions

    @discardableResult
    func tapImport(file: StaticString = #filePath, line: UInt = #line) -> Self {
        importButton.tapWhenReady(file: file, line: line)
        return self
    }

    @discardableResult
    func tapSettings(file: StaticString = #filePath, line: #line) -> SettingsSheetPage {
        settingsButton.tapWhenReady(file: file, line: line)
        return SettingsSheetPage(app: app)
    }

    /// Tap the first available book card, if any.
    @discardableResult
    func tapFirstBook(file: StaticString = #filePath, line: UInt = #line) -> ReaderPage? {
        guard anyBookCard.waitForExistence(timeout: 5) else { return nil }
        anyBookCard.tap()
        return ReaderPage(app: app)
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = #line) {
        importButton.assertExists(file: file, line: line)
    }

    func assertEmptyStateVisible(file: StaticString = #filePath, line: UInt = #line) {
        emptyStateTitle.assertExists(file: file, line: line)
    }
}
