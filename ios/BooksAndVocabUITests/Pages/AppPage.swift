import XCTest

/// Page Object representing the root app shell (tab bar + global chrome).
struct AppPage {
    let app: XCUIApplication

    // MARK: - Tab Bar

    var bookshelfTab: XCUIElement {
        app.tabBars.buttons["tab.bookshelf"]
    }

    var podcastTab: XCUIElement {
        app.tabBars.buttons["tab.podcasts"]
    }

    var notebookTab: XCUIElement {
        app.tabBars.buttons["tab.notebooks"]
    }

    var overviewTab: XCUIElement {
        app.tabBars.buttons["tab.overview"]
    }

    // MARK: - Global Overlays

    var offlineBanner: XCUIElement {
        app.staticTexts["offlineBanner.message"]
    }

    var demoBanner: XCUIElement {
        app.staticTexts["demoBanner.message"]
    }

    // MARK: - Navigation

    @discardableResult
    func goToBookshelf(file: StaticString = #filePath, line: UInt = #line) -> BookshelfPage {
        bookshelfTab.tapWhenReady(file: file, line: line)
        return BookshelfPage(app: app)
    }

    @discardableResult
    func goToPodcasts(file: StaticString = #filePath, line: UInt = #line) -> PodcastPage {
        podcastTab.tapWhenReady(file: file, line: line)
        return PodcastPage(app: app)
    }

    @discardableResult
    func goToNotebooks(file: StaticString = #filePath, line: UInt = #line) -> NotebookPage {
        notebookTab.tapWhenReady(file: file, line: line)
        return NotebookPage(app: app)
    }

    @discardableResult
    func goToOverview(file: StaticString = #filePath, line: UInt = #line) -> OverviewPage {
        overviewTab.tapWhenReady(file: file, line: line)
        return OverviewPage(app: app)
    }

    // MARK: - Assertions

    func assertAllTabsVisible(file: StaticString = #filePath, line: UInt = #line) {
        bookshelfTab.assertExists(file: file, line: line)
        podcastTab.assertExists(file: file, line: line)
        notebookTab.assertExists(file: file, line: line)
        overviewTab.assertExists(file: file, line: line)
    }
}
