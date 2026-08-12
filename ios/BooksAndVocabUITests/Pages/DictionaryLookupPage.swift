import XCTest

/// Page Object for the live dictionary lookup sheet.
///
/// Every state selector is published by `AddLinkSheet`; tests intentionally
/// query the live state element rather than asserting a translated label.
struct DictionaryLookupPage {
    let app: XCUIApplication

    var searchField: XCUIElement {
        app.textFields["addLink.dictionary.searchField"]
    }

    var loadingState: XCUIElement { element("addLink.dictionary.loading") }
    var emptyState: XCUIElement { element("addLink.dictionary.empty") }
    var partialState: XCUIElement { element("addLink.dictionary.partial") }
    var offlineState: XCUIElement { element("addLink.dictionary.offline") }
    var errorState: XCUIElement { element("addLink.dictionary.error") }
    var retryingState: XCUIElement { element("addLink.dictionary.retrying") }
    var retryButton: XCUIElement { app.buttons["addLink.dictionary.retry"] }
    var result: XCUIElement { element("addLink.dictionary.result") }
    var provenance: XCUIElement { element("addLink.dictionary.provenance") }

    func sense(id: String) -> XCUIElement {
        element("addLink.sense.\(id)")
    }

    func example(id: String) -> XCUIElement {
        element("addLink.example.\(id)")
    }

    func materialization(status: String) -> XCUIElement {
        element("addLink.dictionary.materialization.\(status)")
    }

    @discardableResult
    func search(_ query: String, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        searchField.tapWhenReady(file: file, line: line)
        searchField.typeText(query)
        searchField.typeText("\n")
        return self
    }

    @discardableResult
    func waitForSheet(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        XCTAssertTrue(
            searchField.waitUntilExists(timeout: 10),
            "dictionary lookup sheet search field did not mount",
            file: file,
            line: line
        )
        return self
    }

    private func element(_ identifier: String) -> XCUIElement {
        app.descendants(matching: .any)
            .matching(identifier: identifier)
            .firstMatch
    }
}
