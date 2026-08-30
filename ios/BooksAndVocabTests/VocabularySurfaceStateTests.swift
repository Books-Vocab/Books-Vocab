import Foundation
import Testing
@testable import BooksAndVocab

struct VocabularySurfaceStateTests {
    @Test func statsPhase_distinguishesFilteredEmptyFromInitialLoading() {
        #expect(StatsScenePhase.resolve(hasSummary: false, isEmpty: false) == .loading)
        #expect(StatsScenePhase.resolve(hasSummary: true, isEmpty: true) == .empty)
        #expect(StatsScenePhase.resolve(hasSummary: true, isEmpty: false) == .content)
    }

    @Test func reviewCalendar_filterKeepsOnlySelectedNotebookRecords() {
        let kept = ReviewRecord(word: "kept", entryID: nil, feedback: 1)
        kept.notebookId = "keep"
        let removed = ReviewRecord(word: "removed", entryID: nil, feedback: 0)
        removed.notebookId = "remove"

        let result = ReviewCalendarPresentation.filteredRecords(
            [kept, removed],
            filter: NotebookFilter(selectedIds: ["keep"])
        )

        #expect(result.map(\.word) == ["kept"])
    }

    @Test func reviewCalendar_recordsUseDeterministicIDOrderWhenReviewedAtTies() throws {
        let clock = ReviewCalendarClock(
            now: try fixedDate("2026-01-02T12:00:00Z"),
            timeZone: try #require(TimeZone(identifier: "UTC"))
        )
        let reviewedAt = try fixedDate("2026-01-02T10:00:00Z")
        let lowID = try #require(UUID(uuidString: "00000000-0000-0000-0000-000000000001"))
        let highID = try #require(UUID(uuidString: "00000000-0000-0000-0000-000000000002"))
        let lowIDRecord = ReviewRecord(
            word: "low-id",
            entryID: nil,
            feedback: 1,
            reviewedAt: reviewedAt
        )
        lowIDRecord.id = lowID
        let highIDRecord = ReviewRecord(
            word: "high-id",
            entryID: nil,
            feedback: 1,
            reviewedAt: reviewedAt
        )
        highIDRecord.id = highID

        let result = ReviewCalendarPresentation.records(
            for: "2026-01-02",
            from: [highIDRecord, lowIDRecord],
            clock: clock
        )

        #expect(result.map(\.id.uuidString) == [lowID.uuidString, highID.uuidString])
    }

    @Test func reviewCalendar_dayStateSeparatesEmptyFromPopulatedStatus() {
        #expect(ReviewCalendarPresentation.dayState(for: []) == .empty)

        let remembered = ReviewRecord(word: "remembered", entryID: nil, feedback: 1)
        let forgot = ReviewRecord(word: "forgot", entryID: nil, feedback: 0)
        #expect(
            ReviewCalendarPresentation.dayState(for: [remembered, forgot])
                == .populated(total: 2, remembered: 1, forgot: 1)
        )
    }

    @Test func reviewCalendar_projectionUsesInjectedClockAndTimezone() throws {
        let timeZone = try #require(TimeZone(identifier: "America/Los_Angeles"))
        let clock = ReviewCalendarClock(
            now: try fixedDate("2026-01-02T00:30:00Z"),
            timeZone: timeZone
        )
        let beforeLocalMidnight = ReviewRecord(
            word: "before",
            entryID: nil,
            feedback: 1,
            reviewedAt: try fixedDate("2026-01-02T00:30:00Z")
        )
        let afterLocalMidnight = ReviewRecord(
            word: "after",
            entryID: nil,
            feedback: 0,
            reviewedAt: try fixedDate("2026-01-02T08:30:00Z")
        )

        #expect(
            ReviewCalendarPresentation.dayKey(for: beforeLocalMidnight.reviewedAt, clock: clock)
                == "2026-01-01",
            "timezone-boundary-counterexample"
        )
        #expect(
            ReviewCalendarPresentation.dayKey(for: afterLocalMidnight.reviewedAt, clock: clock)
                == "2026-01-02"
        )
        #expect(
            ReviewCalendarPresentation.records(
                for: "2026-01-01",
                from: [beforeLocalMidnight, afterLocalMidnight],
                clock: clock
            ).map(\.word) == ["before"]
        )
    }

    @Test func reviewCalendar_emptyDayCounterexampleRemainsDistinctFromPopulatedDay() throws {
        let clock = ReviewCalendarClock(
            now: try fixedDate("2026-01-02T12:00:00Z"),
            timeZone: try #require(TimeZone(identifier: "UTC"))
        )
        let record = ReviewRecord(
            word: "populated",
            entryID: nil,
            feedback: 1,
            reviewedAt: try fixedDate("2026-01-02T10:00:00Z")
        )

        #expect(
            ReviewCalendarPresentation.dayState(
                for: ReviewCalendarPresentation.records(
                    for: "2026-01-01",
                    from: [record],
                    clock: clock
                )
            ) == .empty,
            "empty-day-counterexample"
        )
        #expect(
            ReviewCalendarPresentation.dayState(
                for: ReviewCalendarPresentation.records(
                    for: "2026-01-02",
                    from: [record],
                    clock: clock
                )
            ) == .populated(total: 1, remembered: 1, forgot: 0)
        )
    }

    @Test func reviewCalendar_activityUsesInjectedStartOfDayCutoff() throws {
        let timeZone = try #require(TimeZone(identifier: "America/Los_Angeles"))
        // 07:30Z is 23:30 on the previous local day. A one-day window must
        // begin at that local day's midnight, not at 07:30Z minus 24 hours.
        let clock = ReviewCalendarClock(
            now: try fixedDate("2026-03-10T07:30:00Z"),
            timeZone: timeZone
        )
        let recordJustAfterLocalMidnight = ReviewRecord(
            word: "cutoff",
            entryID: nil,
            feedback: 1,
            reviewedAt: try fixedDate("2026-03-09T08:05:00Z")
        )

        let activity = ReviewCalendarPresentation.activity(
            for: 1,
            records: [recordJustAfterLocalMidnight],
            clock: clock
        )

        #expect(
            activity["2026-03-09"] == 1,
            "startOfDay cutoff must retain current local-day records before the exact injected now"
        )
    }

    @Test func statsSummaryUsesInjectedClockAcrossMidnightAndTimezone() throws {
        let timeZone = try #require(TimeZone(identifier: "America/Los_Angeles"))
        let clock = ReviewCalendarClock(
            now: try fixedDate("2026-01-02T00:30:00Z"),
            timeZone: timeZone
        )
        let recordBeforeLocalMidnight = ReviewRecord(
            word: "before",
            entryID: nil,
            feedback: 1,
            reviewedAt: try fixedDate("2026-01-01T07:30:00Z")
        )
        let summary = StatsPresentation.buildSummary(
            from: [],
            reviewRecords: [recordBeforeLocalMidnight],
            forecastDays: 1,
            clock: clock
        )

        #expect(summary.reviewedToday == 0, "the record is yesterday in the injected timezone")
        #expect(summary.activity["2025-12-31"] == 1)
        #expect(summary.currentStreak == 1, "yesterday's injected-timezone review remains the current streak")
    }

    @Test func reviewActivityLogQueriesUseInjectedClockForTheWholeChain() throws {
        let timeZone = try #require(TimeZone(identifier: "America/Los_Angeles"))
        let clock = ReviewCalendarClock(
            now: try fixedDate("2026-01-02T08:30:00Z"),
            timeZone: timeZone
        )
        let record = ReviewRecord(
            word: "boundary",
            entryID: nil,
            feedback: 1,
            reviewedAt: try fixedDate("2026-01-02T00:30:00Z")
        )

        #expect(ReviewActivityLog.reviewedToday(records: [record], clock: clock) == 0)
        #expect(ReviewActivityLog.recordsForDay("2026-01-01", from: [record], clock: clock).count == 1)
        #expect(ReviewActivityLog.streaks(records: [record], clock: clock).current == 1)
        #expect(ReviewActivityLog.activity(for: 1, records: [record], clock: clock)["2026-01-01"] == 1)
    }

    private func fixedDate(_ value: String) throws -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return try #require(formatter.date(from: value))
    }

    @Test func notebookListPhase_surfacesEmptySyncFailureAsError() {
        #expect(
            NotebookListPhase.resolve(
                notebookCount: 0,
                hasLoadedOnce: true,
                isLoggedIn: true,
                hasError: true
            ) == .error
        )
        #expect(
            NotebookListPhase.resolve(
                notebookCount: 2,
                hasLoadedOnce: true,
                isLoggedIn: true,
                hasError: true
            ) == .partial
        )
    }
}
