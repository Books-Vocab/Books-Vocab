import XCTest

/// Page Object representing the root app shell (tab bar + global chrome).
struct AppPage {
    let app: XCUIApplication

    // MARK: - Tab Bar

    /// Tab order: 書庫 → 播客 → 單字本 → 統計
    /// Located by L10n label because SwiftUI `.tabItem.accessibilityIdentifier`
    /// does not propagate to the underlying UIKit tab bar item.
    var bookshelfTab: XCUIElement {
        tab("書庫")
    }

    var podcastTab: XCUIElement {
        tab("播客")
    }

    var notebookTab: XCUIElement {
        let identifier = app.tabBars.buttons["tab.notebooks"]
        if identifier.exists { return identifier }
        return tab("單字本")
    }

    var overviewTab: XCUIElement {
        tab("總覽")
    }

    /// Explore（共享牌組庫）—— 第 5 個 tab（`KGFeatureFlags.exploreEnabled`，2026-08-05 起 Release 亦開）。
    var exploreTab: XCUIElement {
        tab("探索")
    }

    // MARK: - Global Overlays

    var offlineBanner: XCUIElement {
        exactlyOne("offlineBanner.message", in: app.staticTexts)
    }

    var demoBanner: XCUIElement {
        exactlyOne("demoBanner.message", in: app.staticTexts)
    }

    // MARK: - Navigation

    @discardableResult
    func goToBookshelf(file: StaticString = #filePath, line: UInt = UInt(#line)) -> BookshelfPage {
        guard let tab = app.tabBars.buttons.matching(identifier: "書庫").exactlyOneElement(
            timeout: 5,
            named: "Bookshelf tab",
            file: file,
            line: line
        ) else { return BookshelfPage(app: app) }
        tab.tapWhenReady(file: file, line: line)
        return BookshelfPage(app: app)
    }

    @discardableResult
    func goToPodcasts(file: StaticString = #filePath, line: UInt = UInt(#line)) -> PodcastPage {
        podcastTab.tapWhenReady(file: file, line: line)
        return PodcastPage(app: app)
    }

    @discardableResult
    func goToNotebooks(file: StaticString = #filePath, line: UInt = UInt(#line)) -> NotebookPage {
        XCTAssertTrue(
            notebookTab.waitUntilHittable(timeout: 8),
            "Notebook tab must be hittable before navigation: \(notebookTab.debugDescription)",
            file: file,
            line: line
        )
        notebookTab.tap()
        return NotebookPage(app: app)
    }

    @discardableResult
    func goToOverview(file: StaticString = #filePath, line: UInt = UInt(#line)) -> OverviewPage {
        overviewTab.tapWhenReady(file: file, line: line)
        return OverviewPage(app: app)
    }

    @discardableResult
    func goToExplore(file: StaticString = #filePath, line: UInt = UInt(#line)) -> AppPage {
        exploreTab.tapWhenReady(file: file, line: line)
        return self
    }

    func exploreElement(identifier: String) -> XCUIElement {
        app.descendants(matching: .any).matching(identifier: identifier).firstMatch
    }

    var exploreLoadingState: XCUIElement { exploreElement(identifier: "explore.loadingState") }
    var exploreLoadedState: XCUIElement { exploreElement(identifier: "explore.loadedState") }
    var exploreEmptyState: XCUIElement { exploreElement(identifier: "explore.emptyState") }
    var exploreErrorState: XCUIElement { exploreElement(identifier: "explore.errorState") }
    var exploreRetryButton: XCUIElement { exploreElement(identifier: "explore.retryButton") }

    func exploreDeck(id: String) -> XCUIElement {
        exploreElement(identifier: "explore.deck.\(id)")
    }

    func exploreAsset(assetID: String) -> XCUIElement {
        exploreElement(identifier: "explore.asset.\(assetID)")
    }

    func exploreDetailCover(deckID: String) -> XCUIElement {
        exploreElement(identifier: "explore.detail.cover.\(deckID)")
    }

    func assertExploreElementIsUnique(
        identifier: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let query = app.descendants(matching: .any).matching(identifier: identifier)
        XCTAssertEqual(
            query.count,
            1,
            "Expected exactly one Explore element for \(identifier), got \(query.count)",
            file: file,
            line: line
        )
    }

    // MARK: - Assertions

    func assertAllTabsVisible(file: StaticString = #filePath, line: UInt = UInt(#line)) {
        bookshelfTab.assertExists(file: file, line: line)
        podcastTab.assertExists(file: file, line: line)
        notebookTab.assertExists(file: file, line: line)
        overviewTab.assertExists(file: file, line: line)
    }

    /// Shell chrome must survive entering a section: tab bar alive (no crash)
    /// and a navigation bar present. Carries over ShellSmokeUITests' intent.
    func assertNavigationChrome(
        on sectionName: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        XCTAssertTrue(
            app.tabBars.element.waitForExistence(timeout: 3),
            "Tab bar vanished after entering \(sectionName) — possible crash",
            file: file,
            line: line
        )
        XCTAssertEqual(
            app.tabBars.count,
            1,
            "P1 shell must expose exactly one tab bar on \(sectionName)",
            file: file,
            line: line
        )
        XCTAssertTrue(
            app.navigationBars.element.waitForExistence(timeout: 5),
            "No navigation bar present on \(sectionName)",
            file: file,
            line: line
        )
        XCTAssertEqual(
            app.navigationBars.count,
            1,
            "P1 shell must expose exactly one navigation bar on \(sectionName)",
            file: file,
            line: line
        )
    }

    private func tab(_ label: String) -> XCUIElement {
        exactlyOne(label, in: app.tabBars.buttons)
    }

    private func exactlyOne(_ identifier: String, in query: XCUIElementQuery) -> XCUIElement {
        let matches = query.matching(identifier: identifier)
        XCTAssertEqual(matches.count, 1, "P1 selector must resolve exactly once: \(identifier)")
        return matches.element
    }
}
