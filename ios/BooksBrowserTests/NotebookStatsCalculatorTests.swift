//
//  NotebookStatsCalculatorTests.swift
//  Books & Vocab Tests
//
//  鎖 NotebookStatsCalculator 的分類分支與聚合行為。
//

import Foundation
import Testing
@testable import BooksBrowser

private func makeEntry(
    notebookId: String = "default",
    reviewCount: Int = 0,
    nextReviewAt: Date = Date().addingTimeInterval(3600),
    lastReviewedAt: Date? = nil,
    dateAdded: Date = Date()
) -> VocabularyEntry {
    let entry = VocabularyEntry(
        word: "w",
        translation: "t",
        context: "c",
        bookTitle: "b"
    )
    entry.notebookId = notebookId
    entry.reviewCount = reviewCount
    entry.nextReviewAt = nextReviewAt
    entry.lastReviewedAt = lastReviewedAt
    entry.dateAdded = dateAdded
    return entry
}

struct NotebookStatsCalculatorTests {

    @Test func computeAggregatesCardCountPerNotebook() {
        let entries = [
            makeEntry(notebookId: "A"),
            makeEntry(notebookId: "A"),
            makeEntry(notebookId: "B"),
        ]
        let stats = NotebookStatsCalculator.compute(entries, pendingEntries: [])
        #expect(stats["A"]?.cardCount == 2)
        #expect(stats["B"]?.cardCount == 1)
    }

    @Test func computeClassifiesDueUnlearnedReviewed() {
        let now = Date()
        let past = now.addingTimeInterval(-3600)
        let future = now.addingTimeInterval(3600)

        let entries = [
            makeEntry(notebookId: "X", reviewCount: 0, nextReviewAt: future), // unlearned
            makeEntry(notebookId: "X", reviewCount: 3, nextReviewAt: past),   // due
            makeEntry(notebookId: "X", reviewCount: 3, nextReviewAt: future), // reviewed
        ]
        let stats = NotebookStatsCalculator.compute(entries, pendingEntries: [], now: now)
        #expect(stats["X"]?.unlearnedCount == 1)
        #expect(stats["X"]?.dueCount == 1)
        #expect(stats["X"]?.reviewedCount == 1)
        #expect(stats["X"]?.cardCount == 3)
    }

    @Test func computeLastActivityPicksLatestOfLastReviewedOrDateAdded() {
        let t0 = Date(timeIntervalSince1970: 1_000_000)
        let t1 = Date(timeIntervalSince1970: 2_000_000)
        let t2 = Date(timeIntervalSince1970: 3_000_000)

        let entries = [
            makeEntry(notebookId: "Z", lastReviewedAt: nil, dateAdded: t1),  // activity = t1
            makeEntry(notebookId: "Z", lastReviewedAt: t2, dateAdded: t0),    // activity = t2
            makeEntry(notebookId: "Z", lastReviewedAt: t0, dateAdded: t0),    // activity = t0
        ]
        let stats = NotebookStatsCalculator.compute(entries, pendingEntries: [])
        #expect(stats["Z"]?.lastActivity == t2)
    }

    @Test func computeAddsPendingCountFromSeparateSource() {
        let synced = [makeEntry(notebookId: "P"), makeEntry(notebookId: "P")]
        let pending = [makeEntry(notebookId: "P"), makeEntry(notebookId: "Q")]
        let stats = NotebookStatsCalculator.compute(synced, pendingEntries: pending)
        #expect(stats["P"]?.cardCount == 2)
        #expect(stats["P"]?.pendingCount == 1)
        #expect(stats["Q"]?.cardCount == 0)
        #expect(stats["Q"]?.pendingCount == 1)
    }

    @Test func filteredPartitionsDueAndUnlearnedAndRespectsFilter() {
        let now = Date()
        let past = now.addingTimeInterval(-3600)
        let future = now.addingTimeInterval(3600)

        let entries = [
            makeEntry(notebookId: "keep", reviewCount: 0, nextReviewAt: future), // unlearned, kept
            makeEntry(notebookId: "keep", reviewCount: 2, nextReviewAt: past),   // due, kept
            makeEntry(notebookId: "keep", reviewCount: 2, nextReviewAt: future), // reviewed, dropped
            makeEntry(notebookId: "skip", reviewCount: 0, nextReviewAt: future), // filtered out
            makeEntry(notebookId: "skip", reviewCount: 2, nextReviewAt: past),   // filtered out
        ]
        let filter = NotebookFilter(selectedIds: ["keep"])
        let (due, unlearned) = NotebookStatsCalculator.filtered(entries, filter: filter, now: now)
        #expect(due.count == 1)
        #expect(unlearned.count == 1)
        #expect(due.allSatisfy { $0.notebookId == "keep" })
        #expect(unlearned.allSatisfy { $0.notebookId == "keep" })
    }

    @Test func filteredWithEmptyFilterIncludesAllNotebooks() {
        let now = Date()
        let entries = [
            makeEntry(notebookId: "A", reviewCount: 0, nextReviewAt: now.addingTimeInterval(60)),
            makeEntry(notebookId: "B", reviewCount: 2, nextReviewAt: now.addingTimeInterval(-60)),
        ]
        let (due, unlearned) = NotebookStatsCalculator.filtered(entries, filter: NotebookFilter(), now: now)
        #expect(due.count == 1)
        #expect(unlearned.count == 1)
    }
}
