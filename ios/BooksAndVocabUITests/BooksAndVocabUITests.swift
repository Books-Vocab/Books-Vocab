//
//  BooksAndVocabUITests.swift
//  Books & Vocab UI Tests
//
//  Core user-journey coverage using Page Object pattern.
//

import XCTest

final class BooksAndVocabUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    // MARK: - Launch & Shell

    @MainActor
    func testLaunchShowsAllTabs() throws {
        let app = makeConfiguredApp()
        app.launch()

        let shell = AppPage(app: app)
        shell.assertAllTabsVisible()
    }

    @MainActor
    func testTabNavigationCyclesThroughAllSections() throws {
        let app = makeConfiguredApp()
        app.launch()

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
            makeConfiguredApp().launch()
        }
    }

    // MARK: - Bookshelf Flows

    @MainActor
    func testBookshelfSettingsSheetOpensAndCloses() throws {
        let app = makeConfiguredApp()
        app.launch()

        let bookshelf = AppPage(app: app).goToBookshelf()
        let settings = bookshelf.tapSettings()
        settings.assertIsPresented()

        let _ = settings.dismiss()
        settings.closeButton.assertDoesNotExist()
    }

    @MainActor
    func testBookshelfEmptyStateVisibleWhenNoBooks() throws {
        let app = makeConfiguredApp()
        app.launchArguments += ["-resetContainer"]
        app.launch()

        let bookshelf = AppPage(app: app).goToBookshelf()
        bookshelf.assertEmptyStateVisible()
    }

    // MARK: - Notebook Flows

    @MainActor
    func testNotebookTabShowsAddButton() throws {
        let app = makeConfiguredApp()
        app.launch()

        let notebooks = AppPage(app: app).goToNotebooks()
        notebooks.assertIsActive()
    }

    // MARK: - Overview Flows

    @MainActor
    func testOverviewTabShowsNavigationTitle() throws {
        let app = makeConfiguredApp()
        app.launch()

        let _ = AppPage(app: app).goToOverview()
        let navTitle = app.navigationBars.staticTexts["總覽"]
        navTitle.assertExists()
    }

    // MARK: - Podcast Flows

    @MainActor
    func testPodcastTabIsAccessible() throws {
        let app = makeConfiguredApp()
        app.launch()

        let podcasts = AppPage(app: app).goToPodcasts()
        podcasts.assertIsActive()
    }

    // MARK: - Bookshelf → Reader Flow

    @MainActor
    func testBookshelfToReaderNavigation() throws {
        let app = makeConfiguredApp()
        app.launch()

        let bookshelf = AppPage(app: app).goToBookshelf()
        guard let reader = bookshelf.tapFirstBook() else {
            throw XCTSkip("無書籍測試資料，無法驗證 Reader 導航")
        }
        reader.assertIsActive()
    }
}
