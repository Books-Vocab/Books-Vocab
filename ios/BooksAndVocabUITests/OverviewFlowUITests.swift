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

        struct ScenarioContext: Decodable {
            struct ReviewClock: Decodable {
                let frozenEpoch: Int
                let anchorDay: String
                let timeZone: String
            }

            let reviewClock: ReviewClock
        }

        let scenarioContext: ScenarioContext?
    }

    let totalCards: Int
    let reviewedToday: Int
    let dueToday: Int
    let activityIsEmpty: Bool
    let clockNow: Date
    let forecastDayKey: String

    static func fromRunner(fixtureID: String) throws -> Self {
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
        guard let seed = document.vocabulary[fixtureID] else {
            throw NSError(domain: "OverviewFixtureProjection", code: 4, userInfo: [
                NSLocalizedDescriptionKey: "\(fixtureID) is missing from the injected UI World",
            ])
        }

        guard let reviewClock = document.scenarioContext?.reviewClock,
              let timeZone = TimeZone(identifier: reviewClock.timeZone)
        else {
            throw NSError(domain: "OverviewFixtureProjection", code: 5, userInfo: [
                NSLocalizedDescriptionKey: "marketing_demo.scenarioContext.reviewClock is missing",
            ])
        }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = timeZone
        // OverviewTab and every child projection consume the canonical
        // scenarioContext clock. Decode the same frozen epoch here for both
        // populated and empty vocabulary seeds; fixture-local latest-review
        // heuristics would diverge from the production composition boundary.
        let clockNow = Date(timeIntervalSince1970: TimeInterval(reviewClock.frozenEpoch))

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
            clockNow: clockNow,
            forecastDayKey: todayKey
        )
    }

    static func vocabListLongFromRunner() throws -> Self {
        try fromRunner(fixtureID: "vocabListLong")
    }
}

final class OverviewFlowUITests: UITestCase {
    override func setUpWithError() throws {
        try super.setUpWithError()
        // This suite launches both the populated and large-text counterexample
        // worlds and captures ten evidence steps. Keep the allowance explicit;
        // XCTest's 60-second default otherwise kills a test that has already
        // reached its final passing assertion.
        executionTimeAllowance = 180
    }

    @MainActor
    func testOverviewStatsRenderFromSeededReviewHistory() throws {
        let app = launchIsolatedApp(
            fixtures: [.vocabulary("statsPopulated")],
            perfLog: "overview"
        )
        captureStep("launch", app: app)

        let shell = AppPage(app: app)
        let overview = try step("overview", app: app) {
            let page = shell.goToOverview()
            XCTAssertTrue(app.waitForNavigationToSettle())
            return page
        }
        try step("metrics", app: app) {
            let expected = try OverviewFixtureProjection.fromRunner(fixtureID: "statsPopulated")
            overview.assertIsActive()
            overview.assertOverviewAccessibilityHierarchy()
            overview.assertMetric("totalCards", value: String(expected.totalCards))
            overview.assertMetric("reviewedToday", value: String(expected.reviewedToday))
            overview.assertMetric("dueToday", value: String(expected.dueToday))
            XCTAssertTrue(shell.overviewTab.isSelected, "總覽 tab did not become selected")
        }

        try step("calendar", app: app) {
            overview.calendar.assertExists(timeout: 10)
        }

        try step("forecast-zero", app: app) {
            let expected = try OverviewFixtureProjection.fromRunner(fixtureID: "statsPopulated")
            overview.scrollToForecastBucket(expected.forecastDayKey)
            overview.assertUniqueForecastContract()
            let bucket = overview.forecastBucket(expected.forecastDayKey)
            bucket.assertExists(timeout: 10)
            XCTAssertTrue((bucket.value as? String)?.contains(String(expected.dueToday)) == true)
        }

        try step("notebook-detour", app: app) {
            let notebooks = shell.goToNotebooks()
            notebooks.assertIsActive()
            XCTAssertTrue(shell.notebookTab.isSelected, "單字本 tab did not become selected")
        }

        try step("overview-reentry", app: app) {
            let expected = try OverviewFixtureProjection.fromRunner(fixtureID: "statsPopulated")
            _ = shell.goToOverview()
            overview.assertMetric("totalCards", value: String(expected.totalCards))
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
            counterexampleOverview.assertOverviewAccessibilityHierarchy()
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
        }
    }

    @MainActor
    func testOverviewEmptyForecastCounterexampleIsVisible() throws {
        let expected = try OverviewFixtureProjection.fromRunner(fixtureID: "statsEmpty")
        let app = launchIsolatedApp(
            fixtures: [.vocabulary("statsEmpty")],
            perfLog: "overview-empty-forecast"
        )
        let overview = try step("overview-empty", app: app) {
            let page = AppPage(app: app).goToOverview()
            XCTAssertTrue(app.waitForNavigationToSettle())
            return page
        }

        try step("forecast-zero-counterexample", app: app) {
            overview.assertOverviewAccessibilityHierarchy()
            overview.assertMetric("totalCards", value: "0")
            overview.assertMetric("reviewedToday", value: "0")
            overview.assertMetric("dueToday", value: "0")
            overview.calendar.assertExists(timeout: 10)
            overview.scrollToForecastBucket(expected.forecastDayKey)
            overview.assertUniqueForecastContract()
            let bucket = overview.forecastBucket(expected.forecastDayKey)
            bucket.assertExists(timeout: 10)
            XCTAssertTrue((bucket.value as? String)?.contains("0") == true)
        }
    }

    private static func vocabListLongProjection() throws -> OverviewFixtureProjection {
        try OverviewFixtureProjection.vocabListLongFromRunner()
    }

}
