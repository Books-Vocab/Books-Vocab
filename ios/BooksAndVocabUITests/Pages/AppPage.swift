import XCTest

/// Page Object representing the root app shell (tab bar + global chrome).
struct AppPage {
    let app: XCUIApplication

    // MARK: - Tab Bar

    /// Tab order: bookshelf → podcasts → notebooks → overview → explore.
    /// Tab labels are localized, so page objects must use the system-image
    /// identifier exposed by the native tab bar rather than a translated title.
    private func tab(
        _ identifier: String,
        systemImage: String,
        fallbackLabel: String
    ) -> XCUIElement {
        // SwiftUI may publish the `.accessibilityIdentifier` attached to the
        // tab content as an `Other` sibling instead of as the `Button` under
        // `tabBars` (notably when the fixture selects a different app
        // language). Resolve the production system-image button from the full
        // AX tree first; do not let the localized tab title become the main
        // navigation contract.
        let imageIdentified = app.descendants(matching: .any)
            .matching(identifier: systemImage)
            .firstMatch
        if imageIdentified.exists {
            return imageIdentified
        }
        let identified = app.descendants(matching: .any)
            .matching(identifier: identifier)
            .firstMatch
        if identified.exists {
            return identified
        }
        return exactlyOne(fallbackLabel, in: app.tabBars.buttons)
    }

    var bookshelfTab: XCUIElement {
        tab("tab.bookshelf", systemImage: "books.vertical", fallbackLabel: "書庫")
    }

    var podcastTab: XCUIElement {
        tab("tab.podcasts", systemImage: "waveform", fallbackLabel: "播客")
    }

    var notebookTab: XCUIElement {
        tab("tab.notebooks", systemImage: "character.book.closed", fallbackLabel: "單字本")
    }

    var overviewTab: XCUIElement {
        tab("tab.overview", systemImage: "chart.bar", fallbackLabel: "總覽")
    }

    /// Explore（共享牌組庫）—— 第 5 個 tab（`KGFeatureFlags.exploreEnabled`，2026-08-05 起 Release 亦開）。
    var exploreTab: XCUIElement {
        tab("tab.explore", systemImage: "sparkles", fallbackLabel: "探索")
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
        bookshelfTab.tapWhenReady(file: file, line: line)
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
    var explorePartialState: XCUIElement { exploreElement(identifier: "explore.partialState") }
    var exploreErrorState: XCUIElement { exploreElement(identifier: "explore.errorState") }
    var exploreRetryButton: XCUIElement { exploreElement(identifier: "explore.retryButton") }

    func exploreDeck(id: String) -> XCUIElement {
        exploreElement(identifier: "explore.deck.\(id)")
    }

    func exploreAsset(assetID: String) -> XCUIElement {
        app.otherElements["explore.asset.\(assetID)"]
    }

    func exploreDetailCover(deckID: String) -> XCUIElement {
        app.images["explore.detail.cover.\(deckID)"]
    }

    func assertExploreAssetIsUnique(
        identifier: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let query = app.otherElements.matching(identifier: identifier)
        XCTAssertEqual(
            query.count,
            1,
            "Expected exactly one Explore asset projection for \(identifier), got \(query.count)",
            file: file,
            line: line
        )
    }

    func assertExploreImageIsUnique(
        identifier: String,
        file: StaticString = #filePath,
        line: UInt = UInt(#line)
    ) {
        let query = app.images.matching(identifier: identifier)
        XCTAssertEqual(
            query.count,
            1,
            "Expected exactly one Explore detail image for \(identifier), got \(query.count)",
            file: file,
            line: line
        )
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

    private func exactlyOne(_ identifier: String, in query: XCUIElementQuery) -> XCUIElement {
        let matches = query.matching(identifier: identifier)
        XCTAssertEqual(matches.count, 1, "P1 selector must resolve exactly once: \(identifier)")
        return matches.element
    }
}
