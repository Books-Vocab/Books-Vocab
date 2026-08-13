import XCTest

/// Page Object for the vocabulary search flow inside a notebook's word list
/// (NotebookListView → drill-down → VocabularyListView / KGVocabView).
///
/// Selectors are accessibility identifiers added for this flow:
/// - `vocab.searchField` / `vocab.searchField.clear` — VocabSearchField
/// - `vocab.row.<word>` — KGVocabRow
/// - `cardDocument.hero.word` — WordDetailSheet hero word (CardDocumentHeroBlock)
struct VocabularySearchPage {
    let app: XCUIApplication

    // MARK: - Search field

    var searchField: XCUIElement {
        app.textFields["vocab.searchField"]
    }

    var searchClearButton: XCUIElement {
        app.buttons["vocab.searchField.clear"]
    }

    // MARK: - Result rows

    /// Vocabulary row: `accessibilityIdentifier = "vocab.row.<word>"`
    func row(word: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: "vocab.row.\(word)").firstMatch
    }

    var anyRow: XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(format: "identifier BEGINSWITH %@", "vocab.row."))
            .firstMatch
    }

    var visibleCount: XCUIElement {
        app.descendants(matching: .any).matching(identifier: "vocab.filter.visibleCount").firstMatch
    }

    var reviewCTA: XCUIElement {
        app.descendants(matching: .any).matching(identifier: "vocab.reviewCTA").firstMatch
    }

    var sortMenu: XCUIElement {
        app.descendants(matching: .any).matching(identifier: "vocab.sort").firstMatch
    }

    /// The report renders review states as direct multi-select pills, not a
    /// hidden menu. This selector is retained as the "review controls exist"
    /// probe used by the flow test.
    var reviewStateControls: XCUIElement {
        app.descendants(matching: .any)
            .matching(identifier: "vocab.filter.reviewState.due")
            .firstMatch
    }

    func scopeOption(
        _ rawValue: String,
        labelPrefix: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> XCUIElement {
        let byID = app.descendants(matching: .any)
            .matching(identifier: "vocab.filter.scope.\(rawValue)")
            .firstMatch
        return byID
    }

    func reviewStateOption(
        _ rawValue: String,
        labelPrefix: String
    ) -> XCUIElement {
        let byID = app.descendants(matching: .any)
            .matching(identifier: "vocab.filter.reviewState.\(rawValue)")
            .firstMatch
        return byID
    }

    func selectScope(
        _ rawValue: String,
        labelPrefix: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        scopeOption(rawValue, labelPrefix: labelPrefix).tapWhenReady(file: file, line: line)
    }

    func selectReviewState(
        _ rawValue: String,
        labelPrefix: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        reviewStateOption(rawValue, labelPrefix: labelPrefix).tapWhenReady(file: file, line: line)
    }

    func clearReviewStates(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        app.descendants(matching: .any)
            .matching(identifier: "vocab.filter.reviewState.clear")
            .firstMatch
            .tapWhenReady(file: file, line: line)
    }

    /// Any rendered row that does NOT match `fragment` — used to prove the
    /// full (unfiltered) list is back after clearing a query.
    func anyRowNotContaining(_ fragment: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(NSPredicate(
                format: "identifier BEGINSWITH %@ AND NOT identifier CONTAINS[c] %@",
                "vocab.row.", fragment
            ))
            .firstMatch
    }

    // MARK: - States

    /// KGVocabEmptyState search-miss title (base localization zh-TW).
    var emptySearchStateTitle: XCUIElement {
        app.staticTexts["沒有符合的單字"]
    }

    /// Word-detail hero word (unique to WordDetailSheet; list rows use WordRow).
    var detailHeroWord: XCUIElement {
        app.staticTexts["cardDocument.hero.word"]
    }

    // MARK: - Actions

    /// Focus the search field and type `query`. Assumes the field is empty —
    /// call `clearSearch()` first when re-querying.
    func search(
        _ query: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        searchField.tapWhenReady(file: file, line: line)
        searchField.typeText(query)
    }

    func clearSearch(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        searchClearButton.tapWhenReady(file: file, line: line)
    }
}
