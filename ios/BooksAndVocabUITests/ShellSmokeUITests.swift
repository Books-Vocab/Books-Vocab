//
//  ShellSmokeUITests.swift
//  Books & Vocab UI Tests
//
//  Feature-agnostic shell smoke: only exercises the root tab bar + navigation
//  chrome. Asserts every tab can be entered, the app does not crash, and a
//  navigation bar is present on each section. Deliberately data-independent —
//  no fixture seeding, no feature internals — so it never collides with the
//  podcast playback harness or any content-dependent flow.
//

import XCTest

final class ShellSmokeUITests: XCTestCase {
    override func setUpWithError() throws {
        continueAfterFailure = false
    }

    @MainActor
    func testAllTabsVisibleOnLaunch() throws {
        let app = makeConfiguredApp()
        app.launch()
        AppPage(app: app).assertAllTabsVisible()
    }

    /// Walk every tab through the shell. Each entry must (1) select the tab,
    /// (2) keep the tab bar alive (no crash), and (3) show a navigation bar.
    @MainActor
    func testEachTabEntersWithNavigationChrome() throws {
        let app = makeConfiguredApp()
        app.launch()

        let shell = AppPage(app: app)
        shell.assertAllTabsVisible()

        let tabs: [(name: String, tab: XCUIElement)] = [
            ("書庫", shell.bookshelfTab),
            ("播客", shell.podcastTab),
            ("單字本", shell.notebookTab),
            ("總覽", shell.overviewTab),
        ]

        for entry in tabs {
            entry.tab.tapWhenReady()
            XCTAssertTrue(
                entry.tab.isSelected,
                "Tab \(entry.name) did not become selected after tap"
            )
            XCTAssertTrue(
                app.tabBars.firstMatch.waitForExistence(timeout: 3),
                "Tab bar vanished after entering \(entry.name) — possible crash"
            )
            XCTAssertTrue(
                app.navigationBars.firstMatch.waitForExistence(timeout: 5),
                "No navigation bar present on \(entry.name) tab"
            )
        }
    }
}
