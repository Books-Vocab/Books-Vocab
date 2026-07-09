#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Pins `StatsPresentation.buildSummary` — the pure-function seam behind the
/// `StatsPresenter` SwiftUI scene. The view itself is `@Query`-driven and
/// `@Environment`-coupled, so it cannot be exercised outside the SwiftUI
/// runtime; `buildSummary` is where every displayed number is computed, so
/// that is the contract this suite locks down.
///
/// Coverage:
///  - card totals: synced filter, delete exclusion, pending exclusion
///  - forecast: bucketing, overdue-collapses-to-today, dueToday, day count
///  - streaks / reviewedToday / activity wiring (via ReviewActivityLog)
///  - adaptive heatmap thresholds (< 4 non-zero days → fallback, else p25/50/75)
///  - the `isSummaryEmpty` invariant that drives the scene's `.empty` phase
///  - boundary inputs: empty data, single record
///
/// All dates are built relative to `Date()` because `buildSummary` formats
/// with `Calendar.current` / `AppDateFormatters.dayKey` in the device time
/// zone — hard-coded calendar dates would be flaky across zones.
struct StatsPresenterTests {

    // MARK: - Helpers

    private static let calendar = Calendar.current

    /// A date `offset` days from now (negative = past), normalized to noon so
    /// `+12h` / `-12h` jitter inside `buildSummary` never crosses a day key.
    private func day(_ offset: Int) -> Date {
        let base = Self.calendar.date(byAdding: .day, value: offset, to: Date()) ?? Date()
        return Self.calendar.date(
            bySettingHour: 12, minute: 0, second: 0, of: base
        ) ?? base
    }

    private func dayKey(_ offset: Int) -> String {
        AppDateFormatters.dayKey.string(from: day(offset))
    }

    /// A synced vocabulary entry whose `nextReviewAt` lands on `dueOffset`
    /// days from today. New `VocabularyEntry` rows default to `syncStatus=0`
    /// (pending), so `buildSummary`'s synced filter would drop them — this
    /// helper flips `syncStatus` to 1 explicitly.
    private func syncedEntry(dueOffset: Int) -> VocabularyEntry {
        let e = VocabularyEntry(
            word: "w\(dueOffset)",
            translation: "t",
            context: "c",
            bookTitle: "B"
        )
        e.syncStatus = 1
        e.nextReviewAt = day(dueOffset)
        return e
    }

    private func review(dayOffset: Int) -> ReviewRecord {
        ReviewRecord(word: "x", entryID: nil, feedback: 1, reviewedAt: day(dayOffset))
    }

    // MARK: - Empty / boundary inputs

    @Test func emptyInput_producesAllZeroSummary() {
        let summary = StatsPresentation.buildSummary(from: [], reviewRecords: [])

        #expect(summary.totalCards == 0)
        #expect(summary.reviewedToday == 0)
        #expect(summary.dueToday == 0)
        #expect(summary.currentStreak == 0)
        #expect(summary.longestStreak == 0)
        #expect(summary.activity.isEmpty)
    }

    /// Mirrors `StatsPresenter.isSummaryEmpty` — an all-zero summary is what
    /// drives the scene into its `.empty` phase. If `buildSummary` ever stopped
    /// producing this shape for empty input, the empty state would never show.
    @Test func emptyInput_satisfiesSceneEmptyInvariant() {
        let s = StatsPresentation.buildSummary(from: [], reviewRecords: [])
        let isEmpty = s.totalCards == 0
            && s.activity.values.allSatisfy { $0 == 0 }
            && s.currentStreak == 0
            && s.longestStreak == 0
        #expect(isEmpty, "empty data must satisfy the scene's `.empty` phase predicate")
    }

    @Test func emptyInput_forecastStillHasDefaultDayCount() {
        let summary = StatsPresentation.buildSummary(from: [], reviewRecords: [])
        // forecastDays defaults to 14 — the forecast array is always fully
        // populated even with no data, so the chart never collapses.
        #expect(summary.forecast.count == 14)
        #expect(summary.forecast.allSatisfy { $0.count == 0 })
    }

    @Test func graphThumbnailBody_usesInlineEmptyAfterLinksLoadWithNoNodes() {
        #expect(
            StatsPresentation.graphThumbnailBodyKind(linksLoaded: true, nodeCount: 0) == .empty,
            "loaded graph links with zero renderable nodes must use the inline empty body, not a nested state card"
        )
    }

    @Test func graphThumbnailBody_distinguishesLoadingEmptyAndGraph() {
        #expect(StatsPresentation.graphThumbnailBodyKind(linksLoaded: false, nodeCount: 0) == .loading)
        #expect(StatsPresentation.graphThumbnailBodyKind(linksLoaded: true, nodeCount: 1) == .graph)
    }

    @Test func singleCard_singleReview_countsAsOne() {
        let summary = StatsPresentation.buildSummary(
            from: [syncedEntry(dueOffset: 0)],
            reviewRecords: [review(dayOffset: 0)]
        )
        #expect(summary.totalCards == 1)
        #expect(summary.reviewedToday == 1)
        #expect(summary.dueToday == 1)
        #expect(summary.currentStreak == 1)
        #expect(summary.longestStreak == 1)
    }

    // MARK: - totalCards filter

    @Test func totalCards_excludesPendingEntries() {
        let pending = VocabularyEntry(word: "p", translation: "t", context: "c", bookTitle: "B")
        // syncStatus left at default 0 → not synced → excluded
        let summary = StatsPresentation.buildSummary(
            from: [pending, syncedEntry(dueOffset: 1)],
            reviewRecords: []
        )
        #expect(summary.totalCards == 1, "only synced entries contribute to totalCards")
    }

    @Test func totalCards_excludesDeleteActionEntries() {
        let toDelete = syncedEntry(dueOffset: 1)
        toDelete.actionType = "delete"
        let summary = StatsPresentation.buildSummary(
            from: [toDelete, syncedEntry(dueOffset: 2)],
            reviewRecords: []
        )
        #expect(summary.totalCards == 1, "synced entries pending deletion must not be counted")
    }

    @Test func totalCards_countsAllSyncedNonDeleteEntries() {
        let entries = (0..<5).map { syncedEntry(dueOffset: $0) }
        let summary = StatsPresentation.buildSummary(from: entries, reviewRecords: [])
        #expect(summary.totalCards == 5)
    }

    // MARK: - Forecast bucketing

    @Test func forecast_dueToday_countsTodayBucket() {
        let summary = StatsPresentation.buildSummary(
            from: [syncedEntry(dueOffset: 0), syncedEntry(dueOffset: 0)],
            reviewRecords: []
        )
        #expect(summary.dueToday == 2)
        #expect(summary.forecast.first?.count == 2)
    }

    @Test func forecast_overdueEntriesCollapseIntoToday() {
        // nextReviewAt in the past → key <= todayKey → folded into today's bucket
        let summary = StatsPresentation.buildSummary(
            from: [syncedEntry(dueOffset: -3), syncedEntry(dueOffset: -10)],
            reviewRecords: []
        )
        #expect(summary.dueToday == 2, "overdue cards must roll forward into today, not vanish")
        #expect(summary.forecast.first?.count == 2)
    }

    @Test func forecast_futureEntryLandsInCorrectBucket() {
        let summary = StatsPresentation.buildSummary(
            from: [syncedEntry(dueOffset: 3)],
            reviewRecords: [],
            forecastDays: 14
        )
        let targetKey = dayKey(3)
        let bucket = summary.forecast.first { $0.id == targetKey }
        #expect(bucket?.count == 1)
        #expect(summary.dueToday == 0, "a card due in 3 days is not due today")
    }

    @Test func forecast_entryBeyondHorizonIsNotBucketed() {
        // Due in 30 days but forecast window is only 7 — it should appear in
        // no bucket, and dueToday stays 0.
        let summary = StatsPresentation.buildSummary(
            from: [syncedEntry(dueOffset: 30)],
            reviewRecords: [],
            forecastDays: 7
        )
        #expect(summary.forecast.count == 7)
        #expect(summary.forecast.allSatisfy { $0.count == 0 })
        #expect(summary.dueToday == 0)
    }

    @Test func forecast_respectsForecastDaysParameter() {
        for days in [7, 14, 30] {
            let summary = StatsPresentation.buildSummary(
                from: [], reviewRecords: [], forecastDays: days
            )
            #expect(summary.forecast.count == days, "forecast length must equal forecastDays=\(days)")
        }
    }

    @Test func forecast_firstTwoBucketsLabeledTodayAndTomorrow() {
        let summary = StatsPresentation.buildSummary(
            from: [], reviewRecords: [], forecastDays: 14
        )
        #expect(summary.forecast[0].label == "今天".localized)
        #expect(summary.forecast[1].label == "明天".localized)
    }

    @Test func forecast_bucketIdsAreDistinctDayKeys() {
        let summary = StatsPresentation.buildSummary(
            from: [], reviewRecords: [], forecastDays: 14
        )
        let ids = Set(summary.forecast.map(\.id))
        #expect(ids.count == 14, "each forecast bucket must have a unique day-key id")
    }

    // MARK: - reviewedToday

    @Test func reviewedToday_countsOnlyTodayRecords() {
        let summary = StatsPresentation.buildSummary(
            from: [],
            reviewRecords: [
                review(dayOffset: 0),
                review(dayOffset: 0),
                review(dayOffset: -1),
                review(dayOffset: -5),
            ]
        )
        #expect(summary.reviewedToday == 2, "only records with today's dayKey count")
    }

    // MARK: - Streaks

    @Test func currentStreak_countsConsecutiveDaysEndingToday() {
        let summary = StatsPresentation.buildSummary(
            from: [],
            reviewRecords: [
                review(dayOffset: 0),
                review(dayOffset: -1),
                review(dayOffset: -2),
            ]
        )
        #expect(summary.currentStreak == 3)
        #expect(summary.longestStreak == 3)
    }

    @Test func currentStreak_survivesMissingTodayButCountsYesterday() {
        // No review today, but yesterday + day-before form a streak. The
        // `offset == 0 → continue` branch lets a not-yet-reviewed today pass.
        let summary = StatsPresentation.buildSummary(
            from: [],
            reviewRecords: [
                review(dayOffset: -1),
                review(dayOffset: -2),
            ]
        )
        #expect(summary.currentStreak == 2, "today not yet reviewed must not reset an active streak")
    }

    @Test func currentStreak_breaksOnGap() {
        // Today + a 2-day gap then older reviews → current streak is just today.
        let summary = StatsPresentation.buildSummary(
            from: [],
            reviewRecords: [
                review(dayOffset: 0),
                review(dayOffset: -3),
                review(dayOffset: -4),
            ]
        )
        #expect(summary.currentStreak == 1)
        #expect(summary.longestStreak == 2, "the older 2-day block is the longest run")
    }

    @Test func longestStreak_picksLongestRunNotMostRecent() {
        let summary = StatsPresentation.buildSummary(
            from: [],
            reviewRecords: [
                review(dayOffset: 0),                       // recent run: 1 day
                review(dayOffset: -10),
                review(dayOffset: -11),
                review(dayOffset: -12),
                review(dayOffset: -13),                     // old run: 4 days
            ]
        )
        #expect(summary.currentStreak == 1)
        #expect(summary.longestStreak == 4)
    }

    @Test func streaks_multipleReviewsSameDayStillCountAsOneDay() {
        let summary = StatsPresentation.buildSummary(
            from: [],
            reviewRecords: [
                review(dayOffset: 0),
                review(dayOffset: 0),
                review(dayOffset: 0),
            ]
        )
        #expect(summary.currentStreak == 1, "a streak counts distinct days, not record volume")
        #expect(summary.reviewedToday == 3, "reviewedToday counts records, not days")
    }

    // MARK: - Frozen clock (injected `now`)
    //
    // ReviewActivityLog 的 streaks / reviewedToday / activity 過去內部取
    // `Date()`，使 `buildSummary(now:)` 的凍結時鐘只凍到 forecast——catalog
    // 快照的 streak / 今日複習卡因牆鐘漂移。這批測試釘住 `now` 全鏈注入。

    @Test func reviewedToday_countsRelativeToInjectedNow() {
        // anchor 遠離牆鐘「今天」→ 若實作偷用 Date()，這裡數不到任何紀錄。
        let anchor = day(-400)
        let records = [ReviewRecord(word: "x", entryID: nil, feedback: 1, reviewedAt: anchor)]

        #expect(ReviewActivityLog.reviewedToday(records: records, now: anchor) == 1)
        #expect(ReviewActivityLog.reviewedToday(records: records) == 0, "wall-clock default must not see a 400-day-old record")
    }

    @Test func streaks_currentStreakAnchorsOnInjectedNow() {
        let anchor = day(-400)
        let records = [
            ReviewRecord(word: "a", entryID: nil, feedback: 1, reviewedAt: anchor),
            ReviewRecord(
                word: "b", entryID: nil, feedback: 1,
                reviewedAt: Self.calendar.date(byAdding: .day, value: -1, to: anchor) ?? anchor
            ),
        ]

        let frozen = ReviewActivityLog.streaks(records: records, now: anchor)
        #expect(frozen.current == 2)
        #expect(frozen.longest == 2)

        let wallClock = ReviewActivityLog.streaks(records: records)
        #expect(wallClock.current == 0, "a 400-day-old run must not count as current against the wall clock")
        #expect(wallClock.longest == 2, "longest streak is clock-independent")
    }

    @Test func activity_cutoffAnchorsOnInjectedNow() {
        let anchor = day(-400)
        let records = [ReviewRecord(word: "x", entryID: nil, feedback: 1, reviewedAt: anchor)]

        let frozen = ReviewActivityLog.activity(for: 180, records: records, now: anchor)
        #expect(frozen.values.reduce(0, +) == 1)

        let wallClock = ReviewActivityLog.activity(for: 180, records: records)
        #expect(wallClock.isEmpty, "a 400-day-old record is outside the wall-clock 180-day window")
    }

    @Test func buildSummary_threadsNowIntoActivityLog() {
        let anchor = day(-400)
        let records = [ReviewRecord(word: "x", entryID: nil, feedback: 1, reviewedAt: anchor)]

        let summary = StatsPresentation.buildSummary(from: [], reviewRecords: records, now: anchor)
        #expect(summary.reviewedToday == 1)
        #expect(summary.currentStreak == 1)
        #expect(summary.activity.values.reduce(0, +) == 1)
    }

    // MARK: - Activity map

    @Test func activity_aggregatesRecordsByDayKey() {
        let summary = StatsPresentation.buildSummary(
            from: [],
            reviewRecords: [
                review(dayOffset: 0),
                review(dayOffset: 0),
                review(dayOffset: -1),
            ]
        )
        #expect(summary.activity[dayKey(0)] == 2)
        #expect(summary.activity[dayKey(-1)] == 1)
    }

    // MARK: - Heatmap thresholds (adaptive percentiles)

    @Test func heatmapThresholds_fallbackWhenFewerThanFourNonZeroDays() {
        // Only 3 distinct review days → fewer than 4 non-zero counts → fallback.
        let summary = StatsPresentation.buildSummary(
            from: [],
            reviewRecords: [
                review(dayOffset: 0),
                review(dayOffset: -1),
                review(dayOffset: -2),
            ]
        )
        #expect(summary.heatmapThresholds == [1, 2, 3], "sparse data must use the simple fallback ramp")
    }

    @Test func heatmapThresholds_emptyInputUsesFallback() {
        let summary = StatsPresentation.buildSummary(from: [], reviewRecords: [])
        #expect(summary.heatmapThresholds == [1, 2, 3])
    }

    @Test func heatmapThresholds_computedFromPercentilesWithEnoughDays() {
        // 8 distinct days with ascending volume 1..8. sorted non-zero counts:
        // [1,2,3,4,5,6,7,8]. p25 = idx 8/4=2 → 3, p50 = idx 4 → 5, p75 = idx 6 → 7.
        var records: [ReviewRecord] = []
        for dayOffset in 0..<8 {
            let volume = dayOffset + 1
            for _ in 0..<volume {
                records.append(review(dayOffset: -dayOffset))
            }
        }
        let summary = StatsPresentation.buildSummary(from: [], reviewRecords: records)
        #expect(summary.heatmapThresholds == [3, 5, 7],
                "with >= 4 non-zero days the ramp must come from p25/p50/p75 of the sorted counts")
    }

    @Test func heatmapThresholds_areNonDescending() {
        // Property check across an irregular distribution.
        var records: [ReviewRecord] = []
        let volumes = [1, 9, 2, 7, 4, 1, 6]
        for (dayOffset, volume) in volumes.enumerated() {
            for _ in 0..<volume { records.append(review(dayOffset: -dayOffset)) }
        }
        let summary = StatsPresentation.buildSummary(from: [], reviewRecords: records)
        let t = summary.heatmapThresholds
        #expect(t.count == 3)
        #expect(t[0] <= t[1] && t[1] <= t[2], "percentile thresholds must be monotonically non-descending")
    }

    // MARK: - Combined / non-empty scene invariant

    @Test func nonEmptyData_failsSceneEmptyInvariant() {
        // A populated summary must NOT satisfy the `.empty` predicate, so the
        // scene resolves to `.content`.
        let s = StatsPresentation.buildSummary(
            from: [syncedEntry(dueOffset: 0)],
            reviewRecords: [review(dayOffset: 0)]
        )
        let isEmpty = s.totalCards == 0
            && s.activity.values.allSatisfy { $0 == 0 }
            && s.currentStreak == 0
            && s.longestStreak == 0
        #expect(!isEmpty, "any card or review activity must push the scene into `.content`")
    }
}

#if DEBUG && canImport(Playbook)
/// Pins `StatsViewTime.anchor` — the catalog Stats View frozen "today" must be
/// derived from the seed's latest review event (寫死日期會讓「複習預測/今日到期」
/// 在 seed 錨日移動後恆 0)。
@Suite struct StatsViewSceneTimeTests {
    @Test func anchorDerivesNoonOfLatestReviewedAt() throws {
        let calendar = Calendar.current
        let latest = try #require(calendar.date(from: DateComponents(year: 2026, month: 7, day: 9, hour: 3, minute: 17)))

        let anchor = StatsViewTime.anchor(latestReviewedAt: latest)

        let comps = calendar.dateComponents([.year, .month, .day, .hour, .minute], from: anchor)
        #expect(comps.year == 2026)
        #expect(comps.month == 7)
        #expect(comps.day == 9)
        #expect(comps.hour == 12)
        #expect(comps.minute == 0)
    }

    @Test func anchorFallsBackDeterministicallyForEmptySeeds() {
        #expect(StatsViewTime.anchor(latestReviewedAt: nil) == StatsViewTime.emptySeedFallback)
    }
}
#endif
#endif
