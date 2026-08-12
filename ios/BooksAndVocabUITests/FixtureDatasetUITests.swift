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
    private enum ReviewCalendarClockSelector {
        static let canonical = "reviewCalendar.clock.history_plan.anchor_day"
        static let live = "reviewCalendar.clock.live"
    }

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
            let now: String?
            let frozenEpoch: Int?
            let anchorDay: String?
            let timeZone: String?
            let source: String?
        }
        struct EvidenceAsset: Decodable {
            let fixtureID: String
            let stepLabel: String
            let index: Int
            let assetIDs: [String]
            let assetInodes: [String]
        }
        struct EvidenceGroups: Decodable {
            let required: [EvidenceAsset]
            let counterexamples: [EvidenceAsset]
        }
        struct GeneratedEvidence: Encodable {
            let fixtureID: String
            let stepLabel: String
            let manifestAssetID: String
            let assetID: String
            let artifactPath: String
            let inode: UInt64
            let group: String
        }
        struct GeneratedEvidenceFile: Encodable {
            let schema: String
            let records: [GeneratedEvidence]
        }
        struct SurfaceContracts: Decodable {
            let reviewCalendar: EvidenceGroups?
        }
        struct ScenarioContext: Decodable {
            let reviewClock: ReviewClock?
            let surfaceContracts: SurfaceContracts?
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
              clock.now != nil,
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
        let evidence = try XCTUnwrap(document.scenarioContext?.surfaceContracts?.reviewCalendar)
        assertManifestEvidenceMapping(evidence)
        XCTAssertEqual(clock.source, "history_plan.anchor_day")
        guard let boundaryDays = timezoneBoundaryDays(
            in: history,
            timeZoneIdentifier: clock.timeZone!
        ) else {
            XCTFail("reviewCalendarDense must include a UTC/local timezone-boundary event")
            return
        }
        XCTAssertNotEqual(
            boundaryDays.utcCount,
            boundaryDays.localCount,
            "UTC/local timezone counterexample must select different day-bucket states"
        )

        let anchorDay = try XCTUnwrap(clock.anchorDay)
        let anchorMonth = monthKey(for: anchorDay)
        let previousMonth = monthKey(for: anchorDay, offset: -1)
        let counts = dayCounts(in: history, timeZoneIdentifier: clock.timeZone!)
        let emptyDay = try XCTUnwrap(
            emptyDay(in: previousMonth, occupied: Set(counts.local.keys)),
            "dense fixture must expose an empty day in the previous month"
        )
        let emptyCounterexampleDay = try XCTUnwrap(
            emptyDay(in: previousMonth, occupied: Set(counts.local.keys), excluding: [emptyDay]),
            "dense fixture must expose a second empty day for the counterexample"
        )
        let populatedMonth = counts.local.keys
            .filter { $0.hasPrefix(previousMonth) }
            .isEmpty ? monthKey(for: boundaryDays.local) : previousMonth
        let populatedDay = try XCTUnwrap(
            mostPopulatedDay(in: populatedMonth, counts: counts.local),
            "dense fixture must expose a populated day"
        )

        var generatedEvidence: [DatasetDocument.GeneratedEvidence] = []
        let app = launchIsolatedApp(fixtures: [.reviewCalendarDense], perfLog: "review-calendar")
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
        assertClockProvenance(in: app)
        generatedEvidence.append(try captureEvidence(
            evidence.required[0], group: "required", app: app
        ))

        // All navigation and day keys are derived from the injected anchor and
        // decoded history; no localized labels or wall-clock dates are used.
        moveCalendar(calendar, from: anchorMonth, to: previousMonth)
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
        generatedEvidence.append(try captureEvidence(
            evidence.required[1], group: "required", app: app
        ))

        moveCalendar(calendar, from: previousMonth, to: populatedMonth)
        guard calendar.day(populatedDay).waitUntilExists(timeout: 5) else {
            XCTFail("dense calendar fixture must expose a populated selectable day")
            return
        }
        calendar.day(populatedDay).tapWhenReady()
        assertPopulatedDay(
            calendar,
            expectedCount: try XCTUnwrap(counts.local[populatedDay]),
            label: "populated-day"
        )
        generatedEvidence.append(try captureEvidence(
            evidence.required[2], group: "required", app: app
        ))
        let requiredBoundaryMonth = monthKey(for: boundaryDays.local)
        moveCalendar(calendar, from: populatedMonth, to: requiredBoundaryMonth)
        calendar.day(boundaryDays.local).tapWhenReady()
        let requiredBoundaryCount = try assertPopulatedDay(
            calendar,
            expectedCount: boundaryDays.localCount,
            label: "timezone-boundary"
        )
        XCTAssertEqual(requiredBoundaryCount, boundaryDays.localCount)
        generatedEvidence.append(try captureEvidence(
            evidence.required[3], group: "required", app: app
        ))

        // Counterexamples are captured from a separate app launch so their
        // screenshot files/inodes cannot alias the required-state evidence.
        app.terminate()
        let counterexampleApp = launchIsolatedApp(
            fixtures: [.reviewCalendarDense],
            perfLog: "review-calendar-counterexamples"
        )
        let counterexampleOverview = AppPage(app: counterexampleApp).goToOverview()
        counterexampleOverview.reviewCalendarButton.tapWhenReady()
        let counterexampleCalendar = ReviewCalendarPage(app: counterexampleApp)
        assertClockProvenance(in: counterexampleApp)
        moveCalendar(counterexampleCalendar, from: anchorMonth, to: previousMonth)
        counterexampleCalendar.day(emptyCounterexampleDay).tapWhenReady()
        counterexampleCalendar.emptyDayDetail.assertExists(timeout: 5)
        generatedEvidence.append(try captureEvidence(
            evidence.counterexamples[0], group: "counterexamples", app: counterexampleApp
        ))
        let counterexampleBoundaryMonth = monthKey(for: boundaryDays.utc)
        moveCalendar(counterexampleCalendar, from: previousMonth, to: counterexampleBoundaryMonth)
        counterexampleCalendar.day(boundaryDays.utc).tapWhenReady()
        let counterexampleBoundaryCount = try assertPopulatedDay(
            counterexampleCalendar,
            expectedCount: boundaryDays.utcCount,
            label: "timezone-boundary-counterexample"
        )
        XCTAssertNotEqual(
            counterexampleBoundaryCount,
            requiredBoundaryCount,
            "UTC/local selected day states must differ, not merely be non-empty"
        )
        generatedEvidence.append(try captureEvidence(
            evidence.counterexamples[1], group: "counterexamples", app: counterexampleApp
        ))

        assertGeneratedEvidence(evidence, records: generatedEvidence)
    }

    private struct DayBucket {
        let utc: String
        let local: String
        let utcCount: Int
        let localCount: Int
    }

    private struct DayCounts {
        let utc: [String: Int]
        let local: [String: Int]
    }

    private func timezoneBoundaryDays(
        in history: [DatasetDocument.ReviewHistoryItem],
        timeZoneIdentifier: String
    ) -> DayBucket? {
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
        var utcCounts: [String: Int] = [:]
        var localCounts: [String: Int] = [:]
        var pairs: Set<String> = []
        for item in history {
            let utc = key(utcCalendar.dateComponents([.year, .month, .day], from: item.reviewedAt))
            let local = key(localCalendar.dateComponents([.year, .month, .day], from: item.reviewedAt))
            guard let utc, let local else { continue }
            utcCounts[utc, default: 0] += 1
            localCounts[local, default: 0] += 1
            if utc != local { pairs.insert("\(utc)|\(local)") }
        }
        return pairs.sorted().compactMap { pair in
            let parts = pair.split(separator: "|", omittingEmptySubsequences: false)
            guard parts.count == 2 else { return nil }
            let utc = String(parts[0])
            let local = String(parts[1])
            let utcCount = utcCounts[utc, default: 0]
            let localCount = localCounts[local, default: 0]
            guard utcCount != localCount else { return nil }
            return DayBucket(utc: utc, local: local, utcCount: utcCount, localCount: localCount)
        }.first
    }

    private func dayCounts(
        in history: [DatasetDocument.ReviewHistoryItem],
        timeZoneIdentifier: String
    ) -> DayCounts {
        guard let timeZone = TimeZone(identifier: timeZoneIdentifier) else {
            return DayCounts(utc: [:], local: [:])
        }
        var utcCalendar = Calendar(identifier: .gregorian)
        utcCalendar.timeZone = TimeZone(secondsFromGMT: 0)!
        var localCalendar = Calendar(identifier: .gregorian)
        localCalendar.timeZone = timeZone
        func key(_ components: DateComponents) -> String? {
            guard let year = components.year, let month = components.month,
                  let day = components.day else { return nil }
            return String(format: "%04d-%02d-%02d", year, month, day)
        }
        var utc: [String: Int] = [:]
        var local: [String: Int] = [:]
        for item in history {
            if let key = key(utcCalendar.dateComponents([.year, .month, .day], from: item.reviewedAt)) {
                utc[key, default: 0] += 1
            }
            if let key = key(localCalendar.dateComponents([.year, .month, .day], from: item.reviewedAt)) {
                local[key, default: 0] += 1
            }
        }
        return DayCounts(utc: utc, local: local)
    }

    private func monthKey(for day: String, offset: Int = 0) -> String {
        let parts = day.split(separator: "-").compactMap { Int($0) }
        guard parts.count >= 2 else { return day }
        let monthIndex = (parts[0] * 12 + parts[1] - 1) + offset
        let year = monthIndex / 12
        let month = monthIndex % 12 + 1
        return String(format: "%04d-%02d", year, month)
    }

    private func dayKeys(in month: String) -> [String] {
        let parts = month.split(separator: "-").compactMap { Int($0) }
        guard parts.count == 2 else { return [] }
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        guard let start = calendar.date(from: DateComponents(year: parts[0], month: parts[1], day: 1)),
              let range = calendar.range(of: .day, in: .month, for: start) else { return [] }
        return range.map { String(format: "%04d-%02d-%02d", parts[0], parts[1], $0) }
    }

    private func emptyDay(
        in month: String,
        occupied: Set<String>,
        excluding: [String] = []
    ) -> String? {
        let excluded = Set(excluding)
        return dayKeys(in: month).first { !occupied.contains($0) && !excluded.contains($0) }
    }

    private func mostPopulatedDay(in month: String, counts: [String: Int]) -> String? {
        counts.filter { $0.key.hasPrefix(month) }
            .sorted { lhs, rhs in lhs.value == rhs.value ? lhs.key < rhs.key : lhs.value > rhs.value }
            .first?.key
    }

    private func moveCalendar(_ page: ReviewCalendarPage, from current: String, to target: String) {
        let currentParts = current.split(separator: "-").compactMap { Int($0) }
        let targetParts = target.split(separator: "-").compactMap { Int($0) }
        guard currentParts.count == 2, targetParts.count == 2 else { return }
        let delta = (targetParts[0] * 12 + targetParts[1]) - (currentParts[0] * 12 + currentParts[1])
        if delta < 0 {
            for _ in 0 ..< -delta { page.previousMonthButton.tapWhenReady() }
        } else {
            for _ in 0 ..< delta { page.nextMonthButton.tapWhenReady() }
        }
    }

    @discardableResult
    private func assertPopulatedDay(
        _ page: ReviewCalendarPage,
        expectedCount: Int,
        label: String
    ) throws -> Int {
        page.populatedDayDetail.assertExists(timeout: 5)
        page.selectedDay.assertExists(timeout: 5)
        page.populatedDaySummary.assertExists(timeout: 5)
        let value = try XCTUnwrap(
            page.populatedDaySummary.value as? String,
            "\(label) summary must expose a numeric accessibility value"
        )
        let actual = try XCTUnwrap(
            Int(value),
            "\(label) summary value must be an integer"
        )
        XCTAssertEqual(actual, expectedCount, "\(label) must expose the selected day bucket count")
        return actual
    }

    private func assertManifestEvidenceMapping(_ evidence: DatasetDocument.EvidenceGroups) {
        XCTAssertEqual(evidence.required.map(\.stepLabel), ReviewCalendarEvidence.requiredLabels)
        XCTAssertEqual(evidence.counterexamples.map(\.stepLabel), ReviewCalendarEvidence.counterexampleLabels)
        let all = evidence.required + evidence.counterexamples
        XCTAssertEqual(all.count, Set(all.map(\.stepLabel)).count, "evidence labels must be unique")
        XCTAssertTrue(
            all.allSatisfy { $0.assetIDs.count == 1 && $0.assetInodes.count == 1 },
            "each label maps to one asset ID and inode"
        )
        XCTAssertEqual(all.count, Set(all.map { $0.assetIDs[0] }).count, "asset IDs must be one-to-one")
        XCTAssertEqual(all.count, Set(all.map { $0.assetInodes[0] }).count, "asset inodes must be one-to-one")
        XCTAssertEqual(
            Set(evidence.required.map { $0.assetIDs[0] }).intersection(Set(evidence.counterexamples.map { $0.assetIDs[0] })),
            [],
            "required/counterexample asset IDs must be disjoint"
        )
        XCTAssertEqual(
            Set(evidence.required.map { $0.assetInodes[0] }).intersection(Set(evidence.counterexamples.map { $0.assetInodes[0] })),
            [],
            "required/counterexample asset inodes must be disjoint"
        )
    }

    private func assertClockProvenance(in app: XCUIApplication) {
        let canonical = app.descendants(matching: .any)[ReviewCalendarClockSelector.canonical]
        let live = app.descendants(matching: .any)[ReviewCalendarClockSelector.live]
        XCTAssertEqual(canonical.count, 1, "UI World must expose canonical history-plan clock provenance")
        XCTAssertEqual(live.count, 0, "UI World must not expose live Date() clock provenance")
    }

    private func captureEvidence(
        _ row: DatasetDocument.EvidenceAsset,
        group: String,
        app: XCUIApplication
    ) throws -> DatasetDocument.GeneratedEvidence {
        XCTAssertEqual(row.assetIDs.count, 1, "evidence row must declare one logical asset ID")
        captureStep(row.stepLabel, app: app)

        guard let rawDirectory = ProcessInfo.processInfo.environment["KG_UI_TEST_SCREENSHOT_DIR"],
              !rawDirectory.isEmpty
        else {
            XCTFail("KG_UI_TEST_SCREENSHOT_DIR is required for generated evidence metadata")
            throw NSError(domain: "P9Evidence", code: 1)
        }
        let directory = URL(fileURLWithPath: rawDirectory)
        let safeLabel = row.stepLabel
            .replacingOccurrences(of: "[^A-Za-z0-9._-]+", with: "-", options: .regularExpression)
            .trimmingCharacters(in: CharacterSet(charactersIn: "-"))
        let artifacts = (try? FileManager.default.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.isRegularFileKey],
            options: [.skipsHiddenFiles]
        ))?.filter {
            $0.pathExtension == "png" &&
            $0.deletingPathExtension().lastPathComponent.hasSuffix("-\(safeLabel)")
        } ?? []
        let artifact = try XCTUnwrap(
            artifacts.sorted { $0.lastPathComponent < $1.lastPathComponent }.last,
            "exactly one generated screenshot is required for \(row.stepLabel)"
        )
        XCTAssertEqual(artifacts.count, 1, "duplicate generated screenshot artifacts must fail")
        let inode = try XCTUnwrap(fileNumber(artifact), "generated screenshot must expose its actual inode")
        return DatasetDocument.GeneratedEvidence(
            fixtureID: row.fixtureID,
            stepLabel: row.stepLabel,
            manifestAssetID: row.assetIDs[0],
            assetID: artifact.deletingPathExtension().lastPathComponent,
            artifactPath: artifact.path,
            inode: inode,
            group: group
        )
    }

    private func assertGeneratedEvidence(
        _ evidence: DatasetDocument.EvidenceGroups,
        records: [DatasetDocument.GeneratedEvidence]
    ) {
        let allRows = evidence.required + evidence.counterexamples
        XCTAssertEqual(records.count, allRows.count, "all manifest evidence rows must bind generated artifacts")
        XCTAssertEqual(Set(records.map(\.assetID)).count, records.count, "generated asset IDs must be unique")
        XCTAssertEqual(Set(records.map(\.inode)).count, records.count, "generated screenshot inodes must be unique")
        let required = Set(records.filter { $0.group == "required" }.map(\.assetID))
        let counterexamples = Set(records.filter { $0.group == "counterexamples" }.map(\.assetID))
        XCTAssertTrue(required.isDisjoint(with: counterexamples), "required/counterexample artifacts must be disjoint")

        let requiredLabelSet = Set(ReviewCalendarEvidence.requiredLabels)
        let counterexampleLabelSet = Set(ReviewCalendarEvidence.counterexampleLabels)
        XCTAssertEqual(
            requiredLabelSet.intersection(counterexampleLabelSet),
            [],
            "required/counterexample step labels must be disjoint"
        )
        XCTAssertEqual(
            requiredLabelSet.count,
            ReviewCalendarEvidence.requiredLabels.count,
            "required step labels must be unique"
        )
        XCTAssertEqual(
            counterexampleLabelSet.count,
            ReviewCalendarEvidence.counterexampleLabels.count,
            "counterexample step labels must be unique"
        )

        guard let rawDirectory = ProcessInfo.processInfo.environment["KG_UI_TEST_SCREENSHOT_DIR"],
              !rawDirectory.isEmpty
        else {
            XCTFail("KG_UI_TEST_SCREENSHOT_DIR is required for machine-verifiable UI World evidence")
            return
        }

        let directory = URL(fileURLWithPath: rawDirectory)
        let manifestURL = directory.appendingPathComponent("p9_review_calendar_evidence.json")
        do {
            let encoder = JSONEncoder()
            encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
            try encoder.encode(DatasetDocument.GeneratedEvidenceFile(
                schema: "kg.p9.review_calendar.evidence.v1",
                records: records
            ))
                .write(to: manifestURL)
        } catch {
            XCTFail("failed to write actual generated evidence metadata: \(error)")
        }

    }

    private func fileNumber(_ url: URL) -> UInt64? {
        guard let attributes = try? FileManager.default.attributesOfItem(atPath: url.path),
              let number = attributes[.systemFileNumber] as? NSNumber
        else { return nil }
        return number.uint64Value
    }
}
