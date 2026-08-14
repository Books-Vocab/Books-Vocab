import XCTest

/// Page Object for the live dictionary lookup sheet.
///
/// Every state selector is published by `AddLinkSheet`; tests intentionally
/// query the live state element rather than asserting a translated label.
struct DictionaryLookupPage {
    let app: XCUIApplication

    private enum CanonicalLookupState: String {
        case idle
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
        exactlyOne("addLink.dictionary.searchField", in: app.textFields)
    }

    var loadingState: XCUIElement { stateMarker(.loading) }
    var releaseLoadingButton: XCUIElement {
        exactlyOne("addLink.dictionary.releaseLoading", in: app.buttons)
    }
    var emptyState: XCUIElement {
        app.descendants(matching: .any)
            .matching(identifier: "addLink.dictionary.empty")
            .firstMatch
    }
    var partialState: XCUIElement { stateMarker(.partial) }
    var offlineState: XCUIElement { stateMarker(.offline) }
    var errorState: XCUIElement { stateMarker(.error) }
    var retryingState: XCUIElement { stateMarker(.retrying) }
    var retryButton: XCUIElement {
        exactlyOne("addLink.dictionary.retry", in: app.buttons)
    }
    var releaseRetryButton: XCUIElement {
        exactlyOne("addLink.dictionary.releaseRetry", in: app.buttons)
    }
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
        let matches = app.descendants(matching: .any).matching(identifier: "addLink.dictionary.\(expected.accessibilitySuffix)")
        XCTAssertEqual(matches.count, 1, "canonical selector must resolve exactly once: \(expected.canonicalFixtureID)", file: file, line: line)
        XCTAssertGreaterThan(marker.frame.width, 0, "canonical selector has no positive width: \(expected.canonicalFixtureID)", file: file, line: line)
        XCTAssertGreaterThan(marker.frame.height, 0, "canonical selector has no positive height: \(expected.canonicalFixtureID)", file: file, line: line)
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

    func tapSense(id: String, file: StaticString = #filePath, line: UInt = UInt(#line)) {
        let target = sense(id: id)
        assertUnique(target, identifier: "addLink.sense.\(id)", file: file, line: line)
        target.tapWhenReady(file: file, line: line)
    }

    func tapExample(id: String, file: StaticString = #filePath, line: UInt = UInt(#line)) {
        let target = example(id: id)
        assertUnique(target, identifier: "addLink.example.\(id)", file: file, line: line)
        target.tapWhenReady(file: file, line: line)
    }

    func tapMaterialize(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        let target = element("addLink.dictionary.materialize")
        assertUnique(target, identifier: "addLink.dictionary.materialize", file: file, line: line)
        target.tapWhenReady(file: file, line: line)
    }

    func releaseRetryRequest(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        assertUnique(
            releaseRetryButton,
            identifier: "addLink.dictionary.releaseRetry",
            file: file,
            line: line
        )
        releaseRetryButton.tapWhenReady(file: file, line: line)
    }

    func assertRetryButton(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        let matches = app.buttons.matching(identifier: "addLink.dictionary.retry")
        XCTAssertEqual(matches.count, 1, "retry action selector must resolve exactly once", file: file, line: line)
        XCTAssertTrue(retryButton.waitUntilHittable(timeout: 5), "retry action must be live and hittable", file: file, line: line)
        XCTAssertGreaterThan(retryButton.frame.width, 0, "retry action has no positive width", file: file, line: line)
        XCTAssertGreaterThan(retryButton.frame.height, 0, "retry action has no positive height", file: file, line: line)
    }

    func releaseLoading(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        releaseLoadingButton.tapWhenReady(file: file, line: line)
    }

    func assertEmptyState(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        XCTAssertTrue(
            emptyState.waitUntilExists(timeout: 10),
            "dictionary empty state marker did not mount",
            file: file,
            line: line
        )
        let matches = app.descendants(matching: .any)
            .matching(identifier: "addLink.dictionary.empty")
        XCTAssertEqual(
            matches.count,
            1,
            "canonical selector must resolve exactly once: addLink.dictionary.empty",
            file: file,
            line: line
        )
        XCTAssertGreaterThan(emptyState.frame.width, 0, "empty state selector has no positive width", file: file, line: line)
        XCTAssertGreaterThan(emptyState.frame.height, 0, "empty state selector has no positive height", file: file, line: line)
        XCTAssertEqual(
            emptyState.value as? String,
            UIWorldDictionaryLookupState.result.fixtureID,
            "empty state AX marker must identify the result fixture",
            file: file,
            line: line
        )
    }

    @discardableResult
    func search(_ query: String, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        enterQuery(query, file: file, line: line)
        submitQuery(file: file, line: line)
        return self
    }

    @discardableResult
    func enterQuery(_ query: String, file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        searchField.tapWhenReady(file: file, line: line)
        searchField.typeText(query)
        return self
    }

    @discardableResult
    func submitQuery(file: StaticString = #filePath, line: UInt = UInt(#line)) -> Self {
        searchField.typeText("\n")
        return self
    }

    var materializationFailure: XCUIElement {
        element("addLink.dictionary.materialization.failed")
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
        exactlyOne(identifier, in: app.descendants(matching: .any))
    }

    private func exactlyOne(_ identifier: String, in query: XCUIElementQuery) -> XCUIElement {
        let matches = query.matching(identifier: identifier)
        XCTAssertEqual(matches.count, 1, "P1 selector must resolve exactly once: \(identifier)")
        return matches.element
    }

    private func stateMarker(_ state: CanonicalLookupState) -> XCUIElement {
        // SwiftUI/List mounts the result marker asynchronously. Resolve a
        // first match now, wait for it to mount, then assert cardinality in
        // `assertCanonicalState`; an eager count here races the AX update.
        app.descendants(matching: .any)
            .matching(identifier: "addLink.dictionary.\(state.accessibilitySuffix)")
            .firstMatch
    }

    private func assertUnique(
        _ element: XCUIElement,
        identifier: String,
        file: StaticString,
        line: UInt
    ) {
        let matches = app.descendants(matching: .any).matching(identifier: identifier)
        XCTAssertEqual(matches.count, 1, "canonical selector must resolve exactly once: \(identifier)", file: file, line: line)
        XCTAssertGreaterThan(element.frame.width, 0, "selector has no positive width: \(identifier)", file: file, line: line)
        XCTAssertGreaterThan(element.frame.height, 0, "selector has no positive height: \(identifier)", file: file, line: line)
    }
}
