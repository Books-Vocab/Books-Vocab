//
//  FixtureDatasetUITests.swift
//  Books & Vocab UI Tests
//
//  End-to-end proof for the `ios_test.sh --dataset <name>` chain:
//  runner env (KG_FIXTURE_DATASET_DEFLATE_B64, or legacy KG_FIXTURE_DATASET_B64)
//  → UITestLaunchConfiguration forwarding → app FixtureDatasetStore
//  → UITestFixtureSeed bookshelf seeder → rendered UI.
//
//  Without a UI World on the runner the test fails; run it via:
//      ./ops/ios_test.sh --ui --dataset marketing_demo -g FixtureDatasetUITests
//

import XCTest

final class FixtureDatasetUITests: UITestCase {
    private enum ReviewCalendarEvidence {
        static let requiredLabels = [
            "calendar",
            "empty-day",
            "populated-day",
            "timezone-boundary",
        ]
        static let counterexampleLabels = [
            "empty-day-counterexample",
            "timezone-boundary-counterexample",
        ]
    }

    /// Minimal mirror of `kg.fixture.dataset.v2` — enough to assert the runner
    /// injected the same required manifest shape the app consumes.
    private struct DatasetDocument: Decodable {
        struct Shelf: Decodable {
            struct Book: Decodable { let title: String }
            let books: [Book]
        }
        struct ReviewClock: Decodable {
            let frozenNow: String?
            let frozenEpoch: Int?
            let anchorDay: String?
            let timeZone: String?
            let source: String?
        }
        struct ScenarioContext: Decodable {
            let reviewClock: ReviewClock?
        }
        struct ReviewHistoryItem: Decodable {
            let reviewedAt: Date
        }
        struct Vocabulary: Decodable {
            let reviewHistory: [ReviewHistoryItem]
        }
        let schema: String
        let datasetID: String
        let bookshelf: [String: Shelf]
        let scenarioContext: ScenarioContext?
        let vocabulary: [String: Vocabulary]
    }

    @MainActor
    func testBookshelfRendersDatasetOverriddenTitle() throws {
        let environment = ProcessInfo.processInfo.environment
        let data: Data
        if let deflateB64 = environment["KG_FIXTURE_DATASET_DEFLATE_B64"], !deflateB64.isEmpty {
            guard let compressed = Data(base64Encoded: deflateB64) else {
                XCTFail("KG_FIXTURE_DATASET_DEFLATE_B64 is not valid base64")
                return
            }
            data = try (compressed as NSData).decompressed(using: .zlib) as Data
        } else if let base64 = environment["KG_FIXTURE_DATASET_B64"], !base64.isEmpty {
            guard let decoded = Data(base64Encoded: base64) else {
                XCTFail("KG_FIXTURE_DATASET_B64 is not valid base64")
                return
            }
            data = decoded
        } else {
            XCTFail("missing UI World on the runner — run via ./ops/ios_test.sh --ui --dataset <name>")
            return
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let document = try decoder.decode(DatasetDocument.self, from: data)
        XCTAssertEqual(document.schema, "kg.fixture.dataset.v2")
        XCTAssertFalse(document.datasetID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        guard let expectedTitle = document.bookshelf["with_books_library"]?.books.first?.title else {
            XCTFail("UI World defines no bookshelf.with_books_library entry")
            return
        }

        let app = launchIsolatedApp(fixtures: [.bookshelf("with_books_library")])
        let shell = AppPage(app: app)
        let bookshelf = shell.goToBookshelf()
        guard bookshelf.anyBookCard.waitUntilExists(timeout: 10) else {
            XCTFail("bookshelf fixture (with_books_library) should render at least one book card")
            return
        }
        XCTAssertTrue(
            app.staticTexts[expectedTitle].waitUntilExists(timeout: 5),
            "dataset-overridden book title '\(expectedTitle)' should render in the bookshelf"
        )
    }

    @MainActor
    func testReviewCalendarRequiredEvidenceUsesStableSelectors() throws {
        let environment = ProcessInfo.processInfo.environment
        let encoded = environment["KG_FIXTURE_DATASET_DEFLATE_B64"]
            ?? environment["KG_FIXTURE_DATASET_B64"]
        guard let encoded, let compressedOrPlain = Data(base64Encoded: encoded) else {
            XCTFail("missing UI World — run with --dataset marketing_demo")
            return
        }
        let data: Data
        if environment["KG_FIXTURE_DATASET_DEFLATE_B64"] != nil {
            data = try (compressedOrPlain as NSData).decompressed(using: .zlib) as Data
        } else {
            data = compressedOrPlain
        }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        let document = try decoder.decode(DatasetDocument.self, from: data)
        guard let clock = document.scenarioContext?.reviewClock,
              clock.frozenNow != nil,
              clock.frozenEpoch != nil,
              clock.anchorDay != nil,
              clock.timeZone != nil,
              clock.source != nil
        else {
            XCTFail("scenarioContext.reviewClock must be explicit; null/fallback clock is not valid evidence")
            return
        }
        let history = try XCTUnwrap(document.vocabulary["reviewCalendarDense"]?.reviewHistory)
        XCTAssertFalse(history.isEmpty, "reviewCalendarDense must provide populated-day evidence")
        guard let boundaryDays = timezoneBoundaryDays(
            in: history,
            timeZoneIdentifier: clock.timeZone!
        ) else {
            XCTFail("reviewCalendarDense must include a UTC/local timezone-boundary event")
            return
        }
        XCTAssertTrue(
            boundaryDays.local.hasPrefix("2026-06-"),
            "timezone-boundary evidence must stay in the dense fixture month"
        )

        let app = launchIsolatedApp(fixtures: [.shellNavigation], perfLog: "review-calendar")
        let overview = AppPage(app: app).goToOverview()
        guard overview.statsContent.waitUntilExists(timeout: 10) else {
            captureStep("calendar", app: app)
            XCTFail("overview content must render before opening Review Calendar")
            return
        }
        overview.reviewCalendarButton.tapWhenReady()
        let calendar = ReviewCalendarPage(app: app)
        guard calendar.monthHeader.waitUntilExists(timeout: 10) else {
            captureStep("calendar", app: app)
            XCTFail("Review Calendar month header must render")
            return
        }
        captureStep("calendar", app: app)

        // The previous month contains an intentionally empty day in the dense
        // history. Its selector is identifier-based; the exact localized text
        // is not part of this contract.
        calendar.previousMonthButton.tapWhenReady()
        let emptyDay = "2026-05-18"
        guard calendar.day(emptyDay).waitUntilExists(timeout: 5) else {
            captureStep("empty-day", app: app)
            XCTFail("dense calendar fixture must expose an empty selectable day")
            return
        }
        calendar.day(emptyDay).tapWhenReady()
        guard calendar.emptyDayDetail.waitUntilExists(timeout: 5) else {
            captureStep("empty-day", app: app)
            XCTFail("empty-day selection must render the empty detail state")
            return
        }
        captureStep("empty-day", app: app)

        calendar.nextMonthButton.tapWhenReady()
        let populatedDay = "2026-06-14"
        guard calendar.day(populatedDay).waitUntilExists(timeout: 5) else {
            XCTFail("dense calendar fixture must expose a populated selectable day")
            return
        }
        calendar.day(populatedDay).tapWhenReady()
        guard calendar.populatedDayDetail.waitUntilExists(timeout: 5) else {
            XCTFail("populated-day selection must render the populated detail state")
            return
        }
        captureStep("populated-day", app: app)
        calendar.day(boundaryDays.local).tapWhenReady()
        calendar.populatedDayDetail.assertExists(timeout: 5)
        captureStep("timezone-boundary", app: app)

        // Counterexamples are captured from a separate app launch so their
        // screenshot files/inodes cannot alias the required-state evidence.
        app.terminate()
        let counterexampleApp = launchIsolatedApp(
            fixtures: [.shellNavigation],
            perfLog: "review-calendar-counterexamples"
        )
        let counterexampleOverview = AppPage(app: counterexampleApp).goToOverview()
        counterexampleOverview.reviewCalendarButton.tapWhenReady()
        let counterexampleCalendar = ReviewCalendarPage(app: counterexampleApp)
        counterexampleCalendar.previousMonthButton.tapWhenReady()
        counterexampleCalendar.day("2026-05-17").tapWhenReady()
        counterexampleCalendar.emptyDayDetail.assertExists(timeout: 5)
        captureStep("empty-day-counterexample", app: counterexampleApp)
        counterexampleCalendar.nextMonthButton.tapWhenReady()
        counterexampleCalendar.day(boundaryDays.utc).tapWhenReady()
        XCTAssertTrue(
            counterexampleCalendar.emptyDayDetail.waitUntilExists(timeout: 5)
                || counterexampleCalendar.populatedDayDetail.waitUntilExists(timeout: 5),
            "UTC bucket counterexample must render a selected-day detail state"
        )
        captureStep("timezone-boundary-counterexample", app: counterexampleApp)

        assertEvidenceGroupsAreDisjoint(
            requiredLabels: ReviewCalendarEvidence.requiredLabels,
            counterexampleLabels: ReviewCalendarEvidence.counterexampleLabels
        )
    }

    private func timezoneBoundaryDays(
        in history: [DatasetDocument.ReviewHistoryItem],
        timeZoneIdentifier: String
    ) -> (utc: String, local: String)? {
        guard let timeZone = TimeZone(identifier: timeZoneIdentifier) else { return nil }
        var utcCalendar = Calendar(identifier: .gregorian)
        utcCalendar.timeZone = TimeZone(secondsFromGMT: 0)!
        var localCalendar = Calendar(identifier: .gregorian)
        localCalendar.timeZone = timeZone
        func key(_ components: DateComponents) -> String? {
            guard let year = components.year,
                  let month = components.month,
                  let day = components.day
            else { return nil }
            return String(format: "%04d-%02d-%02d", year, month, day)
        }
        return history.lazy.compactMap { item in
            let utc = key(utcCalendar.dateComponents([.year, .month, .day], from: item.reviewedAt))
            let local = key(localCalendar.dateComponents([.year, .month, .day], from: item.reviewedAt))
            guard let utc, let local, utc != local else { return nil }
            return (utc: utc, local: local)
        }.first
    }

    private func assertEvidenceGroupsAreDisjoint(
        requiredLabels: [String],
        counterexampleLabels: [String]
    ) {
        let requiredLabelSet = Set(requiredLabels)
        let counterexampleLabelSet = Set(counterexampleLabels)
        XCTAssertEqual(
            requiredLabelSet.intersection(counterexampleLabelSet),
            [],
            "required/counterexample step labels must be disjoint"
        )
        XCTAssertEqual(
            requiredLabelSet.count,
            requiredLabels.count,
            "required step labels must be unique"
        )
        XCTAssertEqual(
            counterexampleLabelSet.count,
            counterexampleLabels.count,
            "counterexample step labels must be unique"
        )

        guard let rawDirectory = ProcessInfo.processInfo.environment["KG_UI_TEST_SCREENSHOT_DIR"],
              !rawDirectory.isEmpty
        else {
            XCTFail("KG_UI_TEST_SCREENSHOT_DIR is required for machine-verifiable UI World evidence")
            return
        }

        let directory = URL(fileURLWithPath: rawDirectory)
        let pngs = (try? FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ))?.filter { $0.pathExtension == "png" } ?? []

        func assets(for label: String) -> [URL] {
            pngs.filter { $0.deletingPathExtension().lastPathComponent.hasSuffix("-\(label)") }
        }

        let requiredAssets = requiredLabels.flatMap { assets(for: $0) }
        let counterexampleAssets = counterexampleLabels.flatMap { assets(for: $0) }
        XCTAssertEqual(
            Set(requiredAssets.map { $0.deletingPathExtension().lastPathComponent })
                .intersection(Set(counterexampleAssets.map { $0.deletingPathExtension().lastPathComponent })),
            [],
            "required/counterexample asset IDs must be disjoint"
        )
        XCTAssertEqual(requiredAssets.count, requiredLabels.count, "every required step must have one asset")
        XCTAssertEqual(
            counterexampleAssets.count,
            counterexampleLabels.count,
            "every counterexample step must have one asset"
        )

        let requiredInodes = requiredAssets.compactMap { fileNumber($0) }
        let counterexampleInodes = counterexampleAssets.compactMap { fileNumber($0) }
        XCTAssertEqual(
            requiredInodes.count,
            requiredAssets.count,
            "every required asset must expose a filesystem inode"
        )
        XCTAssertEqual(
            counterexampleInodes.count,
            counterexampleAssets.count,
            "every counterexample asset must expose a filesystem inode"
        )
        XCTAssertEqual(
            Set(requiredInodes).intersection(Set(counterexampleInodes)),
            [],
            "required/counterexample asset inodes must be disjoint"
        )
    }

    private func fileNumber(_ url: URL) -> UInt64? {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              let number = attributes[.systemFileNumber] as? NSNumber
        else { return nil }
        return number.uint64Value
    }
}
