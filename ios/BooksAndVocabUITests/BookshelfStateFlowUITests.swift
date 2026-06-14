//
//  BookshelfStateFlowUITests.swift
//  Books & Vocab UI Tests
//
//  Focused Bookshelf state flow: captures the guest empty state and a seeded
//  populated-library state as separate evidence steps in one flow.
//

import XCTest

final class BookshelfStateFlowUITests: UITestCase {
    @MainActor
    func testBookshelfEmptyAndPopulatedStatesRenderExpectedChrome() throws {
        let emptyApp = launchApp(profile: .clean, perfLog: "bookshelf-empty")
        captureStep("empty-launch", app: emptyApp)

        let emptyShell = AppPage(app: emptyApp)
        let emptyBookshelf = try step("empty-bookshelf", app: emptyApp) {
            let page = emptyShell.goToBookshelf()
            page.assertIsActive()
            page.assertEmptyStateVisible()
            XCTAssertTrue(page.emptyStateImportButton.waitUntilExists(timeout: 5))
            XCTAssertTrue(AuthPage(app: emptyApp).bookshelfLoginEntry.waitUntilExists(timeout: 5))
            XCTAssertFalse(
                page.anyBookCard.waitUntilExists(timeout: 1),
                "clean bookshelf state must not render a book card"
            )
            return page
        }
        try step("empty-toolbar", app: emptyApp) {
            emptyBookshelf.settingsButton.assertExists()
        }
        emptyApp.terminate()

        let populatedApp = launchIsolatedApp(
            fixtures: [.bookshelf("with_books_library")],
            perfLog: "bookshelf-populated"
        )
        captureStep("populated-launch", app: populatedApp)

        let populatedShell = AppPage(app: populatedApp)
        let populatedBookshelf = try step("populated-bookshelf", app: populatedApp) {
            let page = populatedShell.goToBookshelf()
            page.assertIsActive()
            XCTAssertTrue(
                page.anyBookCard.waitUntilExists(timeout: 10),
                "with_books_library fixture must render at least one real book card"
            )
            XCTAssertTrue(
                page.emptyState.waitUntilGone(timeout: 5),
                "populated bookshelf must not keep the empty state visible"
            )
            return page
        }

        try step("populated-book-card", app: populatedApp) {
            populatedBookshelf.anyBookCard.assertExists()
        }
    }
}
