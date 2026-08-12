import XCTest

/// Page Object for the live dictionary lookup sheet.
///
/// Every state selector is published by `AddLinkSheet`; tests intentionally
/// query the live state element rather than asserting a translated label.
struct DictionaryLookupPage {
    let app: XCUIApplication

    private enum CanonicalLookupState: String {
        case loading
        case result
        case partial
        case offline
        case error
        case retrying

        var canonicalFixtureID: String {
            let state = self == .retrying ? "retry" : rawValue
            return "dictionary.lookup.\(state)"
        }

        var accessibilitySuffix: String { rawValue }
    }

    var searchField: XCUIElement {
        app.textFields["addLink.dictionary.searchField"]
    }

    var loadingState: XCUIElement { stateMarker(.loading) }
    var emptyState: XCUIElement { element("addLink.dictionary.empty") }
    var partialState: XCUIElement { stateMarker(.partial) }
    var offlineState: XCUIElement { stateMarker(.offline) }
    var errorState: XCUIElement { stateMarker(.error) }
    var retryingState: XCUIElement { stateMarker(.retrying) }
    var retryButton: XCUIElement { app.buttons["addLink.dictionary.retry"] }
    var result: XCUIElement { stateMarker(.result) }
    var provenance: XCUIElement { element("addLink.dictionary.provenance") }

    @discardableResult
    func assertCanonicalState(
        _ state: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) -> Self {
        guard let expected = CanonicalLookupState(rawValue: state) else {
            XCTFail("unknown canonical dictionary state: \(state)", file: file, line: line)
            return self
        }
        let marker = stateMarker(expected)
        XCTAssertTrue(
            marker.waitUntilExists(timeout: 10),
            "dictionary state marker did not mount: \(expected.canonicalFixtureID)",
            file: file,
            line: line
        )
        XCTAssertEqual(
            marker.value as? String,
            expected.canonicalFixtureID,
            "dictionary AX marker must identify the canonical lookup fixture",
            file: file,
            line: line
        )
        return self
    }

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

    private func stateMarker(_ state: CanonicalLookupState) -> XCUIElement {
        element("addLink.dictionary.\(state.accessibilitySuffix)")
    }
}
