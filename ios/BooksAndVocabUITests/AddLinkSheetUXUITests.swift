import XCTest

/// Add Link sheet UX contracts (#2031, #2037, #2038, #2039) on the
/// `vocabLinkedCards` UI World: source `serendipity`, linkable `epiphany`,
/// `fortuitous`, `fortunate`, `revelation`, `happy accident`.
///
/// The server is the unreachable port-9 default, so any network mutation the
/// sheet starts fails fast and deterministically; tests assert on which
/// mutation started, never on a success the backend would have to provide.
final class AddLinkSheetUXUITests: UITestCase {
    private static let notebookID = "ui-vocab-linked-cards-notebook"

    override func setUpWithError() throws {
        try super.setUpWithError()
        XCUIDevice.shared.orientation = .portrait
    }

    // MARK: - #2031

    @MainActor
    func testAddLinkSearchFieldIsFocusedWhenSheetOpens() throws {
        guard let app = openAddLinkSheet(perfLog: "add-link-autofocus") else { return }
        let searchField = app.textFields["addLink.searchField"]

        XCTAssertTrue(
            searchField.waitUntilValue(hasKeyboardFocus: true, timeout: 5),
            "opening Add Link must focus the search field without an extra tap"
        )
        XCTAssertTrue(app.keyboards.firstMatch.waitUntilExists(timeout: 5), "keyboard must be up")
        // Typing without tapping the field proves the focus is real.
        app.typeText("fort")
        XCTAssertEqual(searchField.value as? String, "fort")
        XCTAssertTrue(lookupState(in: app).waitUntilValueEquals("results-2", timeout: 5))
        captureStep("add-link-autofocus", app: app)
    }

    // MARK: - Helpers

    /// Launches the linked-cards world, opens `serendipity`'s detail and its
    /// Add Link sheet. Returns nil after recording a failure.
    @MainActor
    func openAddLinkSheet(
        extraEnvironment: [String: String] = [:],
        perfLog: String
    ) -> XCUIApplication? {
        let app = launchIsolatedApp(
            fixtures: [.vocabulary("vocabLinkedCards")],
            extraEnvironment: extraEnvironment,
            perfLog: perfLog
        )
        let notebooks = AppPage(app: app).goToNotebooks()
        guard notebooks.waitForNotebookCard(id: Self.notebookID, timeout: 10) else {
            XCTFail("AddLink fixture 必須種出 notebook " + Self.notebookID)
            return nil
        }
        notebooks.notebookCard(id: Self.notebookID).tapWhenReady()
        XCTAssertTrue(app.waitForNavigationToSettle())

        let page = VocabularySearchPage(app: app)
        guard page.searchField.waitUntilExists(timeout: 10) else {
            XCTFail("AddLink fixture 必須渲染 vocabulary search field")
            return nil
        }
        page.search("serendipity")
        guard page.waitForRowMaterialized(word: "serendipity", timeout: 10) else {
            XCTFail("AddLink fixture 必須 materialize source row serendipity")
            return nil
        }
        page.row(word: "serendipity").tapWhenReady()

        guard let trigger = app.buttons
            .matching(NSPredicate(format: "label == %@", "新增知識連結"))
            .exactlyOneElement(timeout: 10, named: "AddLink detail trigger") else {
            return nil
        }
        trigger.tapWhenReady()
        guard app.textFields["addLink.searchField"].waitUntilExists(timeout: 5) else {
            XCTFail("word detail 必須開啟 AddLink sheet")
            return nil
        }
        return app
    }

    func lookupState(in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: "addLink.lookup.state").firstMatch
    }

    func marker(_ identifier: String, in app: XCUIApplication) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }
}

private extension XCUIElement {
    /// `hasKeyboardFocus` is the XCUIElement attribute XCTest itself uses to
    /// route `typeText`; polling it avoids a fixed sleep.
    func waitUntilValue(hasKeyboardFocus expected: Bool, timeout: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if exists, (value(forKey: "hasKeyboardFocus") as? Bool) == expected { return true }
            RunLoop.current.run(until: Date().addingTimeInterval(0.1))
        }
        return exists && (value(forKey: "hasKeyboardFocus") as? Bool) == expected
    }
}
