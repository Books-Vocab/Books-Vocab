//
//  OverviewFlowUITests.swift
//  Books & Vocab UI Tests
//
//  Focused Overview flow: proves the stats tab renders real seeded content,
//  and that leaving/re-entering the tab keeps the content surface alive.
//

import Foundation
import XCTest

private struct OverviewFixtureProjection {
    private struct Dataset: Decodable {
        struct Vocabulary: Decodable {
            struct Entry: Decodable {
                let syncStatus: Int
                let actionType: String
                let isArchived: Bool
                let nextReviewAt: Date?
            }

            struct Review: Decodable {
                let reviewedAt: Date
            }

            let entries: [Entry]
            let reviewHistory: [Review]
        }

        let vocabulary: [String: Vocabulary]
    }

    let totalCards: Int
    let reviewedToday: Int
    let dueToday: Int
    let activityIsEmpty: Bool
    let clockNow: Date

    static func vocabListLongFromRunner() throws -> Self {
        let environment = ProcessInfo.processInfo.environment
        let data: Data
        if let deflateB64 = environment["KG_FIXTURE_DATASET_DEFLATE_B64"], !deflateB64.isEmpty {
            guard let compressed = Data(base64Encoded: deflateB64) else {
                throw NSError(domain: "OverviewFixtureProjection", code: 1, userInfo: [
                    NSLocalizedDescriptionKey: "KG_FIXTURE_DATASET_DEFLATE_B64 is not valid base64",
                ])
            }
            data = try (compressed as NSData).decompressed(using: .zlib) as Data
        } else if let base64 = environment["KG_FIXTURE_DATASET_B64"], !base64.isEmpty {
            guard let decoded = Data(base64Encoded: base64) else {
                throw NSError(domain: "OverviewFixtureProjection", code: 2, userInfo: [
                    NSLocalizedDescriptionKey: "KG_FIXTURE_DATASET_B64 is not valid base64",
                ])
            }
            data = decoded
        } else {
            throw NSError(domain: "OverviewFixtureProjection", code: 3, userInfo: [
                NSLocalizedDescriptionKey: "marketing_demo UI World is missing from the runner",
            ])
        }

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let document = try decoder.decode(Dataset.self, from: data)
        guard let seed = document.vocabulary["vocabListLong"] else {
            throw NSError(domain: "OverviewFixtureProjection", code: 4, userInfo: [
                NSLocalizedDescriptionKey: "vocabListLong is missing from the injected UI World",
            ])
        }

        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0) ?? calendar.timeZone
        guard let earliestDueDate = seed.entries.compactMap(\.nextReviewAt).min(),
              let dayAfterDueDate = calendar.date(byAdding: .day, value: 1, to: earliestDueDate),
              let clockNow = calendar.date(
                  bySettingHour: 12,
                  minute: 0,
                  second: 0,
                  of: dayAfterDueDate
              ) else {
            throw NSError(domain: "OverviewFixtureProjection", code: 5, userInfo: [
                NSLocalizedDescriptionKey: "vocabListLong has no derivable due-date clock",
            ])
        }

        func dayKey(_ date: Date) -> String {
            let components = calendar.dateComponents([.year, .month, .day], from: date)
            return String(
                format: "%04d-%02d-%02d",
                components.year ?? 0,
                components.month ?? 0,
                components.day ?? 0
            )
        }

        let todayKey = dayKey(clockNow)
        let visibleEntries = seed.entries.filter {
            $0.syncStatus == 1 && $0.actionType != "delete" && !$0.isArchived
        }
        let dueToday = visibleEntries.filter {
            guard let nextReviewAt = $0.nextReviewAt else { return false }
            return dayKey(nextReviewAt) <= todayKey
        }.count
        let reviewedToday = seed.reviewHistory.filter { dayKey($0.reviewedAt) == todayKey }.count

        return Self(
            totalCards: visibleEntries.count,
            reviewedToday: reviewedToday,
            dueToday: dueToday,
            activityIsEmpty: seed.reviewHistory.isEmpty,
            clockNow: clockNow
        )
    }
}

final class OverviewFlowUITests: UITestCase {
    @MainActor
    func testOverviewStatsRenderFromSeededReviewHistory() throws {
        let app = launchIsolatedApp(
            fixtures: [.vocabulary("statsPopulated")],
            perfLog: "overview"
        )
        captureStep("launch", app: app)

        let shell = AppPage(app: app)
        let overview = try step("overview-tab", app: app) {
            let page = shell.goToOverview()
            XCTAssertTrue(app.waitForNavigationToSettle())
            return page
        }
        try step("metrics", app: app) {
            overview.assertIsActive()
            overview.assertStatsAccessibilityHierarchy()
            XCTAssertTrue(
                overview.statsContent.waitUntilExists(timeout: 10),
                "statsPopulated fixture must render overview.statsContent from seeded review records"
            )
            overview.metrics.assertExists(timeout: 10)
            overview.assertMetric("totalCards", value: "8")
            overview.assertMetric("reviewedToday", value: "2")
            overview.assertMetric("dueToday", value: "0")
            XCTAssertTrue(shell.overviewTab.isSelected, "總覽 tab did not become selected")
        }

        try step("calendar", app: app) {
            overview.calendar.assertExists(timeout: 10)
        }

        try step("forecast-zero", app: app) {
            overview.assertUniqueForecastContract()
            let bucket = overview.forecastBucket("2026-06-02")
            bucket.assertExists(timeout: 10)
            XCTAssertTrue((bucket.value as? String)?.contains("8") == true)
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

        let counterexampleExpected = try Self.vocabListLongProjection()
        let counterexampleApp = launchIsolatedApp(
            extraArgs: [
                "-UIPreferredContentSizeCategoryName",
                "UICTContentSizeCategoryAccessibilityXXXL",
            ],
            fixtures: [.vocabulary("vocabListLong")],
            perfLog: "overview-counterexamples"
        )
        captureStep("large-text-counterexample", app: counterexampleApp)
        attachText(
            "fixture=marketing_demo.vocabListLong\n"
                + "clock=\(counterexampleExpected.clockNow.ISO8601Format())\n"
                + "clockSource=UITestFixtureSeed.makeStatsProjectionClock\n"
                + "clockRule=UTC noon on day after canonical earliest nextReviewAt\n"
                + "dateFallback=none",
            named: "Overview Clock Provenance"
        )
        let counterexampleOverview = try step("large-counts", app: counterexampleApp) {
            let page = AppPage(app: counterexampleApp).goToOverview()
            XCTAssertTrue(counterexampleApp.waitForNavigationToSettle())
            return page
        }
        try step("large-counts-projection", app: counterexampleApp) {
            counterexampleOverview.assertStatsAccessibilityHierarchy()
            counterexampleOverview.metrics.assertExists(timeout: 10)
            counterexampleOverview.assertMetric("totalCards", value: String(counterexampleExpected.totalCards))
            counterexampleOverview.assertMetric("reviewedToday", value: String(counterexampleExpected.reviewedToday))
            counterexampleOverview.assertMetric("dueToday", value: String(counterexampleExpected.dueToday))
            counterexampleOverview.calendar.assertExists(timeout: 10)
            XCTAssertEqual(
                counterexampleOverview.calendar.value as? String,
                counterexampleExpected.activityIsEmpty ? "0" : "populated"
            )
            counterexampleOverview.assertUniqueForecastContract()
            counterexampleOverview.assertForecastContainsCount(String(counterexampleExpected.dueToday))
            counterexampleOverview.largeCounts.assertExists(timeout: 10)
            XCTAssertEqual(
                counterexampleOverview.largeCounts.value as? String,
                String(counterexampleExpected.totalCards)
            )
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
        let expected = try Self.vocabListLongProjection()
        let app = launchIsolatedApp(
            extraArgs: [
                "-UIPreferredContentSizeCategoryName",
                "UICTContentSizeCategoryAccessibilityXXXL",
            ],
            fixtures: [.vocabulary("vocabListLong")],
            perfLog: "overview-counterexamples"
        )
        captureStep("launch-large-accessibility-text", app: app)
        attachText(
            "fixture=marketing_demo.vocabListLong\n"
                + "clock=\(expected.clockNow.ISO8601Format())\n"
                + "clockSource=UITestFixtureSeed.makeStatsProjectionClock\n"
                + "clockRule=UTC noon on day after canonical earliest nextReviewAt\n"
                + "dateFallback=none",
            named: "Overview Clock Provenance"
        )
        let overview = try step("overview-counterexamples", app: app) {
            let page = AppPage(app: app).goToOverview()
            XCTAssertTrue(app.waitForNavigationToSettle())
            return page
        }

        try step("assert-zero-and-large", app: app) {
            overview.assertStatsAccessibilityHierarchy()
            overview.metrics.assertExists(timeout: 10)
            overview.assertMetric("totalCards", value: String(expected.totalCards))
            overview.assertMetric("reviewedToday", value: String(expected.reviewedToday))
            overview.assertMetric("dueToday", value: String(expected.dueToday))
            overview.calendar.assertExists(timeout: 10)
            XCTAssertEqual(overview.calendar.value as? String, expected.activityIsEmpty ? "0" : "populated")
            overview.assertUniqueForecastContract()
            overview.assertForecastContainsCount(String(expected.dueToday))
            overview.largeCounts.assertExists(timeout: 10)
            XCTAssertEqual(overview.largeCounts.value as? String, String(expected.totalCards))
        }
    }

    private static func vocabListLongProjection() throws -> OverviewFixtureProjection {
        try OverviewFixtureProjection.vocabListLongFromRunner()
    }
}
