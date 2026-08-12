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

    @MainActor
    func testOverviewStatsSelectorsExposePopulatedMetricsCalendarAndForecast() throws {
        let app = launchIsolatedApp(
            fixtures: [.vocabulary("statsPopulated")],
            perfLog: "overview-populated"
        )
        let overview = try step("overview-populated", app: app) {
            let page = AppPage(app: app).goToOverview()
            XCTAssertTrue(app.waitForNavigationToSettle())
            return page
        }

        try step("assert-populated-projection", app: app) {
            overview.assertStatsAccessibilityHierarchy()
            overview.metrics.assertExists(timeout: 10)
            overview.assertMetric("totalCards", value: "8")
            overview.assertMetric("reviewedToday", value: "2")
            overview.assertMetric("dueToday", value: "0")
            overview.calendar.assertExists(timeout: 10)
            overview.assertUniqueForecastContract()
            let bucket = overview.forecastBucket("2026-06-02")
            bucket.assertExists(timeout: 10)
            XCTAssertTrue((bucket.value as? String)?.contains("8") == true)
        }
    }

    @MainActor
    func testOverviewStatsSelectorsExposeZeroForecastAndLargeCountCounterexamples() throws {
        let app = launchIsolatedApp(
            fixtures: [.vocabulary("vocabListLong")],
            perfLog: "overview-counterexamples"
        )
        let overview = try step("overview-counterexamples", app: app) {
            let page = AppPage(app: app).goToOverview()
            XCTAssertTrue(app.waitForNavigationToSettle())
            return page
        }

        try step("assert-zero-and-large", app: app) {
            overview.assertStatsAccessibilityHierarchy()
            overview.metrics.assertExists(timeout: 10)
            overview.assertMetric("totalCards", value: "40")
            overview.assertMetric("reviewedToday", value: "0")
            overview.assertMetric("dueToday", value: "0")
            overview.calendar.assertExists(timeout: 10)
            XCTAssertEqual(overview.calendar.value as? String, "0")
            overview.assertUniqueForecastContract()
            overview.largeCounts.assertExists(timeout: 10)
            XCTAssertEqual(overview.largeCounts.value as? String, "40")
        }
    }
}
