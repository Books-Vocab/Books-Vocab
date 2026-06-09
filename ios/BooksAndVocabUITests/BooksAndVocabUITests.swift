//
//  BooksAndVocabUITests.swift
//  Books & Vocab UI Tests
//
//  Created by 陳亮宇 on 2026/2/24.
//

import XCTest

final class BooksAndVocabUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testLaunchShowsPrimaryTabs() throws {
        let app = makeConfiguredApp()
        app.launch()

        XCTAssertTrue(app.tabBars.buttons["書庫"].waitForExistence(timeout: 5))
        XCTAssertTrue(app.tabBars.buttons["單字本"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testBookshelfSettingsSheetOpens() throws {
        let app = makeConfiguredApp()
        app.launch()

        let settingsButton = app.buttons["bookshelf.settingsButton"]
        XCTAssertTrue(settingsButton.waitForExistence(timeout: 5))
        settingsButton.tap()

        XCTAssertTrue(app.navigationBars["設定"].waitForExistence(timeout: 5))
    }

    @MainActor
    func testLaunchPerformance() throws {
        measure(metrics: [XCTApplicationLaunchMetric()]) {
            makeConfiguredApp().launch()
        }
    }
}
