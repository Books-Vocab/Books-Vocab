//
//  NotebookSmokeUITests.swift
//  Books & Vocab UI Tests
//
//  Feature-agnostic notebook smoke: the 單字本 tab is reachable and shows its
//  baseline chrome (add button + navigation bar) regardless of whether any
//  notebooks exist. No card content is asserted — that stays in the
//  data-dependent journey tests — so this never needs fixture seeding.
//

import XCTest

final class NotebookSmokeUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testNotebookTabIsVisibleWithChrome() throws {
        let app = makeConfiguredApp()
        app.launch()

        let notebooks = AppPage(app: app).goToNotebooks()
        notebooks.assertIsActive()  // notebook.addButton exists

        XCTAssertTrue(
            app.navigationBars.firstMatch.waitForExistence(timeout: 5),
            "Notebook tab presented without a navigation bar"
        )
    }

    @MainActor
    func testNotebookAddButtonIsHittable() throws {
        let app = makeConfiguredApp()
        app.launch()

        let notebooks = AppPage(app: app).goToNotebooks()
        notebooks.addButton.assertExists()
        XCTAssertTrue(
            notebooks.addButton.isHittable,
            "Notebook add button exists but is not hittable"
        )
    }
}
