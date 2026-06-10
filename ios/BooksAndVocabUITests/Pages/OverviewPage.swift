import XCTest

/// Page Object for the Overview (Stats) tab.
struct OverviewPage {
    let app: XCUIApplication

    // MARK: - Content

    /// Rendered stats dashboard (only present when the summary computed from
    /// synced entries + review records is non-empty — i.e. real content phase,
    /// not loading / empty / logged-out).
    var statsContent: XCUIElement {
        app.descendants(matching: .any)["overview.statsContent"].firstMatch
    }

    // MARK: - Assertions

    func assertIsActive(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        // Overview has a NavigationStack with a large title in both logged-in and logged-out states.
        let navBar = app.navigationBars.firstMatch
        navBar.assertExists(timeout: 3, file: file, line: line)
    }
}
