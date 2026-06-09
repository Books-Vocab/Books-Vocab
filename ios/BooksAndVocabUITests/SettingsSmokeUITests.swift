//
//  SettingsSmokeUITests.swift
//  Books & Vocab UI Tests
//
//  Feature-agnostic settings smoke: open the Settings sheet from the bookshelf
//  toolbar and close it. Asserts the sheet presents (Done button + nav bar) and
//  fully dismisses. No specific toggle is driven — this guards the entry/exit
//  path, not any one preference — so it stays stable as settings content evolves.
//

import XCTest

final class SettingsSmokeUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testSettingsSheetOpensAndCloses() throws {
        let app = makeConfiguredApp()
        app.launch()

        let bookshelf = AppPage(app: app).goToBookshelf()
        let settings = bookshelf.tapSettings()

        // Presented: Done button + a navigation bar inside the sheet.
        settings.assertIsPresented()
        XCTAssertTrue(
            app.navigationBars.firstMatch.waitForExistence(timeout: 5),
            "Settings sheet presented without a navigation bar"
        )

        // Closed: dismissing returns to bookshelf and the Done button is gone.
        let _ = settings.dismiss()
        settings.closeButton.assertDoesNotExist()
        bookshelf.assertIsActive()
    }
}
