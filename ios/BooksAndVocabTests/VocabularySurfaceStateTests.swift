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
