//
//  OverviewFlowUITests.swift
//  Books & Vocab UI Tests
//
//  Focused Overview flow: proves the stats tab renders real seeded content,
//  and that leaving/re-entering the tab keeps the content surface alive.
//

import XCTest

final class OverviewFlowUITests: UITestCase {
    @MainActor
    func testOverviewStatsRenderFromSeededReviewHistory() throws {
        let app = launchIsolatedApp(
            fixtures: [.shellNavigation],
            perfLog: "overview"
        )
        captureStep("launch", app: app)

        let shell = AppPage(app: app)
        let overview = try step("overview-tab", app: app) {
            let page = shell.goToOverview()
            XCTAssertTrue(app.waitForNavigationToSettle())
            return page
        }
        try step("stats-content", app: app) {
            overview.assertIsActive()
            XCTAssertTrue(
                overview.statsContent.waitUntilExists(timeout: 10),
                "shell navigation fixture must render overview.statsContent from seeded review records"
            )
            XCTAssertTrue(shell.overviewTab.isSelected, "總覽 tab did not become selected")
        }

        try step("notebook-detour", app: app) {
            let notebooks = shell.goToNotebooks()
            notebooks.assertIsActive()
            XCTAssertTrue(shell.notebookTab.isSelected, "單字本 tab did not become selected")
        }

        try step("overview-reentry", app: app) {
            _ = shell.goToOverview()
            XCTAssertTrue(
                overview.statsContent.waitUntilExists(timeout: 5),
                "overview stats content should survive a tab detour"
            )
            XCTAssertTrue(shell.overviewTab.isSelected, "總覽 tab did not become selected on re-entry")
        }
    }
}
