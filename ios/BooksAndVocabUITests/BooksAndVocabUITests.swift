//
//  BooksAndVocabUITests.swift
//  Books & Vocab UI Tests
//
//  Core user-journey coverage using Page Object pattern.
//

import XCTest

final class BooksAndVocabUITests: UITestCase {

    // MARK: - Launch & Shell

    @MainActor
    func testLaunchShowsAllTabs() throws {
        let app = launchApp()

        let shell = AppPage(app: app)
        shell.assertAllTabsVisible()
    }

    @MainActor
    func testTabNavigationCyclesThroughAllSections() throws {
        let app = launchApp()

        let shell = AppPage(app: app)

        // Bookshelf
        let bookshelf = shell.goToBookshelf()
        bookshelf.assertIsActive()

        // Podcasts
        let podcasts = shell.goToPodcasts()
        podcasts.assertIsActive()

        // Notebooks
        let notebooks = shell.goToNotebooks()
        notebooks.assertIsActive()

        // Overview
        let overview = shell.goToOverview()
        overview.assertIsActive()

        // Return to bookshelf — should still be valid
        let bookshelf2 = shell.goToBookshelf()
        bookshelf2.assertIsActive()
    }

    @MainActor
    func testLaunchPerformance() throws {
        measure(metrics: [XCTApplicationLaunchMetric()]) {
            makeConfiguredApp(perfLog: "render,scroll").launch()
        }
    }

    // MARK: - Bookshelf Flows

    @MainActor
    func testBookshelfSettingsSheetOpensAndCloses() throws {
        let app = launchApp()

        let bookshelf = AppPage(app: app).goToBookshelf()
        let settings = bookshelf.tapSettings()
        settings.assertIsPresented()

        let _ = settings.dismiss()
        settings.closeButton.assertDoesNotExist()
    }

    @MainActor
    func testBookshelfEmptyStateVisibleWhenNoBooks() throws {
        let app = launchApp(profile: .clean)

        let bookshelf = AppPage(app: app).goToBookshelf()
        bookshelf.assertEmptyStateVisible()
    }

    // MARK: - Notebook Flows

    @MainActor
    func testNotebookTabShowsAddButton() throws {
        let app = launchApp()

        let notebooks = AppPage(app: app).goToNotebooks()
        notebooks.assertIsActive()
    }

    // MARK: - Overview Flows

    @MainActor
    func testOverviewTabShowsNavigationTitle() throws {
        let app = launchApp()

        let _ = AppPage(app: app).goToOverview()
        XCTAssertTrue(app.waitForNavigationToSettle())
        let navTitle = app.navigationBars.staticTexts["總覽"]
        navTitle.assertExists()
    }

    // MARK: - Podcast Flows

    @MainActor
    func testPodcastTabIsAccessible() throws {
        let app = launchApp()

        let _ = AppPage(app: app).goToPodcasts()
        XCTAssertTrue(app.waitForNavigationToSettle())
        XCTAssertEqual(currentTabSummary(in: app), "播客")
    }

    // MARK: - Bookshelf → Reader Flow

    @MainActor
    func testBookshelfToReaderNavigation() throws {
        // `BookshelfFixtureID` 是 String-raw enum，rawValue 為 snake_case
        // (`with_books_library`)。這裡原本傳 case 名稱 `withBooksLibrary`，
        // `BookshelfFixtureID(rawValue:)` 解不出來 → `failFixtureSeed` 直接 trap，
        // app 在 `BooksAndVocabApp.init()` 就崩，測試從未真的跑到書架。
        let app = launchApp(extraArgs: ["-seedFixture:bookshelf:with_books_library"])

        let bookshelf = AppPage(app: app).goToBookshelf()
        guard let reader = bookshelf.tapFirstBook() else {
            XCTFail("bookshelf.withBooksLibrary fixture should render at least one book")
            return
        }
        reader.assertIsActive()
    }
}
