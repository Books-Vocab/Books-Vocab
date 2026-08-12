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
