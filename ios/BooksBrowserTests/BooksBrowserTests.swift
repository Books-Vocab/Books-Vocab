//
//  BooksBrowserTests.swift
//  BooksBrowserTests
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Foundation
import SwiftData
import Testing
@testable import BooksBrowser

struct BooksBrowserTests {
    @Test @MainActor func todayReviewStateRestoresProgressAcrossSessionReload() async throws {
        TodayReviewSessionSnapshotStore.clear(for: nil)
        let container = try ModelContainer(
            for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        let context = ModelContext(container)

        let first = VocabularyEntry(word: "lucid", translation: "清晰", context: "A lucid answer.", bookTitle: "Sample")
        first.kgCardId = "card-lucid"
        first.markSynced()
        let second = VocabularyEntry(word: "evoke", translation: "喚起", context: "Evoke memory.", bookTitle: "Sample")
        second.kgCardId = "card-evoke"
        second.markSynced()
        context.insert(first)
        context.insert(second)
        #expect(context.safeSave())

        let state = TodayReviewState(
            entries: [first, second],
            allEntries: [first, second],
            currentUserID: "user-1"
        )
        state.submit(.remembered, container: container, reviewSettings: .default)
        try await Task.sleep(for: .milliseconds(100))

        let replacementFirst = VocabularyEntry(word: "lucid", translation: "清晰", context: "A lucid answer.", bookTitle: "Sample")
        replacementFirst.kgCardId = "card-lucid"
        replacementFirst.markSynced()
        let replacementSecond = VocabularyEntry(word: "evoke", translation: "喚起", context: "Evoke memory.", bookTitle: "Sample")
        replacementSecond.kgCardId = "card-evoke"
        replacementSecond.markSynced()
        let restored = TodayReviewState(
            entries: [replacementFirst, replacementSecond],
            allEntries: [replacementFirst, replacementSecond],
            currentUserID: "user-1"
        )

        #expect(restored.currentIndex == 1)
        #expect(restored.rememberedCount == 1)
        #expect(restored.forgotCount == 0)
        #expect(restored.progressText == "2 / 2")
        TodayReviewSessionSnapshotStore.clear(for: nil)
    }

    @Test @MainActor func todayReviewStateFlushesAnswerOncePerCard() async throws {
        TodayReviewSessionSnapshotStore.clear(for: nil)
        let container = try ModelContainer(
            for: VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        let context = ModelContext(container)

        let first = VocabularyEntry(word: "lucid", translation: "清晰", context: "A lucid answer.", bookTitle: "Sample")
        first.kgCardId = "card-lucid"
        first.markSynced()
        let second = VocabularyEntry(word: "evoke", translation: "喚起", context: "Evoke memory.", bookTitle: "Sample")
        second.kgCardId = "card-evoke"
        second.markSynced()
        context.insert(first)
        context.insert(second)
        #expect(context.safeSave())

        let state = TodayReviewState(
            entries: [first, second],
            allEntries: [first, second],
            currentUserID: "user-1"
        )
        state.submit(.remembered, container: container, reviewSettings: .default)
        state.goPrevious()
        state.submit(.forgot, container: container, reviewSettings: .default)
        try await Task.sleep(for: .milliseconds(100))

        let entry = try context.fetch(FetchDescriptor<VocabularyEntry>()).first { $0.kgCardId == "card-lucid" }
        let records = try context.fetch(FetchDescriptor<ReviewRecord>())

        #expect(entry?.reviewCount == 1)
        #expect(entry?.lastReviewFeedbackRaw == ReviewFeedback.remembered.rawValue)
        #expect(records.count == 1)
        #expect(state.currentIndex == 1)
        TodayReviewSessionSnapshotStore.clear(for: nil)
    }

    @Test func readerBridgePlannerEmitsSingleWordHighlightCommand() async throws {
        var planner = ReadiumNavigatorView.Coordinator.BridgePlanner()
        let base = makeSnapshot(lookedUpWords: [])
        _ = planner.makeCommands(from: base)

        let commands = planner.makeCommands(from: makeSnapshot(lookedUpWords: ["resilient"]))

        #expect(commands.contains { command in
            if case .dom(.markNewVocabWord("resilient")) = command { return true }
            return false
        })
    }

    @Test func readerBridgePlannerClearsAndReappliesOnLargeRemoval() async throws {
        var planner = ReadiumNavigatorView.Coordinator.BridgePlanner()
        let originalWords = (0..<12).map { "word\($0)" }
        _ = planner.makeCommands(from: makeSnapshot(lookedUpWords: originalWords))

        let commands = planner.makeCommands(from: makeSnapshot(lookedUpWords: ["word1"]))

        #expect(commands.contains { command in
            if case .dom(.clearAllVocabHighlights) = command { return true }
            return false
        })
        #expect(commands.contains { command in
            if case .dom(.markVocabWords(let words)) = command {
                return words == ["word1"]
            }
            return false
        })
    }

    @Test func readerBridgePlannerOnlyClearsHighlightOncePerTrigger() async throws {
        var planner = ReadiumNavigatorView.Coordinator.BridgePlanner()
        let trigger = UUID()

        let first = planner.makeCommands(from: makeSnapshot(lookedUpWords: [], clearHighlightTrigger: trigger))
        let second = planner.makeCommands(from: makeSnapshot(lookedUpWords: [], clearHighlightTrigger: trigger))

        #expect(first.contains { command in
            if case .dom(.clearActiveHighlight) = command { return true }
            return false
        })
        #expect(second.contains { command in
            if case .dom(.clearActiveHighlight) = command { return true }
            return false
        } == false)
    }

    @Test func vocabularyEntryPendingAddLifecycleIsVisibleInReaderButNotKnowledgeList() async throws {
        let entry = VocabularyEntry(
            word: "evoke",
            translation: "喚起",
            context: "The story can evoke old memories.",
            bookTitle: "Sample"
        )

        entry.restorePendingEntry()

        #expect(entry.isPending)
        #expect(entry.isPendingAdd)
        #expect(entry.shouldUploadOnNextSync)
        #expect(entry.shouldAppearInReader)
        #expect(entry.shouldAppearInKnowledgeList == false)
    }

    @Test func vocabularyEntryPendingDeleteLifecycleHidesFromReaderUntilServerDeleteCompletes() async throws {
        let entry = VocabularyEntry(
            word: "lucid",
            translation: "清晰的",
            context: "Her explanation was lucid.",
            bookTitle: "Sample"
        )

        entry.markSynced()
        entry.queueDelete()

        #expect(entry.isPending)
        #expect(entry.isPendingDelete)
        #expect(entry.shouldUploadOnNextSync)
        #expect(entry.shouldAppearInReader == false)
        #expect(entry.shouldAppearInKnowledgeList == false)
    }

    @Test func vocabularyEntryFailedDeleteRemainsRetryableAndHidden() async throws {
        let entry = VocabularyEntry(
            word: "obsolete",
            translation: "過時",
            context: "That term is obsolete.",
            bookTitle: "Sample"
        )

        entry.markSynced()
        entry.queueDelete()
        entry.markSyncFailed()

        #expect(entry.isFailed)
        #expect(entry.isFailedDelete)
        #expect(entry.shouldUploadOnNextSync)
        #expect(entry.shouldAppearInReader == false)
        #expect(entry.shouldAppearInKnowledgeList == false)
    }

    @Test func vocabularyEntryFailedAddCanReturnToPendingForRetry() async throws {
        let entry = VocabularyEntry(
            word: "evoke",
            translation: "喚起",
            context: "The story can evoke old memories.",
            bookTitle: "Sample"
        )

        entry.restorePendingEntry()
        entry.markSyncFailed()
        entry.prepareForRetryAttempt()

        #expect(entry.isPending)
        #expect(entry.isPendingAdd)
        #expect(entry.shouldUploadOnNextSync)
    }

    @Test func vocabularyEntryPresentationSeparatesPendingQueueFromKnowledgeLibrary() async throws {
        let pendingAdd = VocabularyEntry(
            word: "evoke",
            translation: "喚起",
            context: "The story can evoke old memories.",
            bookTitle: "Sample"
        )
        pendingAdd.restorePendingEntry()

        let synced = VocabularyEntry(
            word: "lucid",
            translation: "清晰的",
            context: "Her explanation was lucid.",
            bookTitle: "Sample"
        )
        synced.markSynced()

        let pendingDelete = VocabularyEntry(
            word: "obsolete",
            translation: "過時",
            context: "That term is obsolete.",
            bookTitle: "Sample"
        )
        pendingDelete.markSynced()
        pendingDelete.queueDelete()

        let failedAdd = VocabularyEntry(
            word: "resilient",
            translation: "有韌性的",
            context: "She stayed resilient.",
            bookTitle: "Sample"
        )
        failedAdd.restorePendingEntry()
        failedAdd.markSyncFailed()

        let entries = [pendingAdd, synced, pendingDelete, failedAdd]

        #expect(VocabularyEntryPresentation.pendingEntries(in: entries).map(\.word).sorted() == ["evoke", "obsolete", "resilient"])
        let classified = VocabularyEntryPresentation.classifyKnowledgeEntries(in: entries, now: Date())
        let allSynced = classified.dueBucket + classified.unlearnedBucket + classified.reviewedBucket
        #expect(allSynced.map(\.word) == ["lucid"])
    }

    // MARK: - mutateLink / insertLink helpers

    @Test func mutateLinkReplacesExistingLink() {
        let entry = VocabularyEntry(word: "test", translation: "測試", context: "ctx", bookTitle: "B")
        let link = KGCardLinkSummary(id: "link-1", cardId: "c1", word: "alpha", kind: "synonym", label: "synonym", confidence: 0.9, reason: "test")
        entry.graphLinksByKind = ["synonym": [link]]

        let result = entry.mutateLink(id: "link-1") { $0.withHidden(true) }

        #expect(result != nil)
        #expect(result?.kind == "synonym")
        #expect(result?.original.isHidden == false)
        #expect(entry.graphLinksByKind["synonym"]?.first?.isHidden == true)
    }

    @Test func mutateLinkRemovesLinkWhenTransformReturnsNil() {
        let entry = VocabularyEntry(word: "test", translation: "測試", context: "ctx", bookTitle: "B")
        let link = KGCardLinkSummary(id: "link-1", cardId: "c1", word: "alpha", kind: "synonym", label: "synonym", confidence: 0.9, reason: "test")
        entry.graphLinksByKind = ["synonym": [link]]

        let result = entry.mutateLink(id: "link-1") { _ in nil }

        #expect(result != nil)
        #expect(result?.original.id == "link-1")
        // group should be cleaned up
        #expect(entry.graphLinksByKind["synonym"] == nil)
    }

    @Test func mutateLinkReturnsNilWhenNotFound() {
        let entry = VocabularyEntry(word: "test", translation: "測試", context: "ctx", bookTitle: "B")
        entry.graphLinksByKind = [:]

        let result = entry.mutateLink(id: "nonexistent") { $0.withHidden(true) }

        #expect(result == nil)
    }

    @Test func insertLinkAddsToCorrectKindGroup() {
        let entry = VocabularyEntry(word: "test", translation: "測試", context: "ctx", bookTitle: "B")
        let existing = KGCardLinkSummary(id: "link-1", cardId: "c1", word: "alpha", kind: "synonym", label: "synonym", confidence: 0.9, reason: "test")
        entry.graphLinksByKind = ["synonym": [existing]]

        let newLink = KGCardLinkSummary(id: "link-2", cardId: "c2", word: "beta", kind: "antonym", label: "antonym", confidence: 0.8, reason: "test")
        entry.insertLink(newLink, kind: "antonym")

        #expect(entry.graphLinksByKind["antonym"]?.count == 1)
        #expect(entry.graphLinksByKind["antonym"]?.first?.id == "link-2")
        #expect(entry.graphLinksByKind["synonym"]?.count == 1)
    }

    // MARK: - Bilateral hide/unhide/delete tests

    private func makeBilateralPair() -> (a: VocabularyEntry, b: VocabularyEntry, linkAtoB: KGCardLinkSummary, linkBtoA: KGCardLinkSummary) {
        let a = VocabularyEntry(word: "lucid", translation: "清晰", context: "ctx", bookTitle: "B")
        a.kgCardId = "card-a"
        let b = VocabularyEntry(word: "vivid", translation: "鮮明", context: "ctx", bookTitle: "B")
        b.kgCardId = "card-b"

        let linkAtoB = KGCardLinkSummary(id: "link-1", cardId: "card-b", word: "vivid", kind: "synonym", label: "同義", confidence: 0.9, reason: "test")
        let linkBtoA = KGCardLinkSummary(id: "link-1", cardId: "card-a", word: "lucid", kind: "synonym", label: "同義", confidence: 0.9, reason: "test")

        a.graphLinksByKind = ["synonym": [linkAtoB]]
        b.graphLinksByKind = ["synonym": [linkBtoA]]

        return (a, b, linkAtoB, linkBtoA)
    }

    @Test func bilateralHideOptimisticUpdateUpdatesBothEntries() {
        let (a, b, _, _) = makeBilateralPair()

        _ = a.mutateLink(id: "link-1") { $0.withHidden(true) }
        _ = b.mutateLink(id: "link-1") { $0.withHidden(true) }

        #expect(a.graphLinksByKind["synonym"]?.first?.isHidden == true)
        #expect(b.graphLinksByKind["synonym"]?.first?.isHidden == true)
    }

    @Test func bilateralHideRollbackRestoresBothEntriesOnAPIFailure() {
        let (a, b, _, _) = makeBilateralPair()

        let resultA = a.mutateLink(id: "link-1") { $0.withHidden(true) }
        let resultB = b.mutateLink(id: "link-1") { $0.withHidden(true) }

        // Simulate API failure → rollback using originals
        if let rA = resultA {
            _ = a.mutateLink(id: "link-1") { _ in rA.original }
        }
        if let rB = resultB {
            _ = b.mutateLink(id: "link-1") { _ in rB.original }
        }

        #expect(a.graphLinksByKind["synonym"]?.first?.isHidden == false)
        #expect(b.graphLinksByKind["synonym"]?.first?.isHidden == false)
    }

    @Test func bilateralUnhideOptimisticUpdateUpdatesBothEntries() {
        let (a, b, _, _) = makeBilateralPair()

        // First hide both
        _ = a.mutateLink(id: "link-1") { $0.withHidden(true) }
        _ = b.mutateLink(id: "link-1") { $0.withHidden(true) }

        // Now unhide both
        _ = a.mutateLink(id: "link-1") { $0.withHidden(false) }
        _ = b.mutateLink(id: "link-1") { $0.withHidden(false) }

        #expect(a.graphLinksByKind["synonym"]?.first?.isHidden == false)
        #expect(b.graphLinksByKind["synonym"]?.first?.isHidden == false)
    }

    @Test func bilateralUnhideRollbackRestoresBothEntriesOnAPIFailure() {
        let (a, b, _, _) = makeBilateralPair()

        // Start hidden
        _ = a.mutateLink(id: "link-1") { $0.withHidden(true) }
        _ = b.mutateLink(id: "link-1") { $0.withHidden(true) }

        // Optimistic unhide
        let resultA = a.mutateLink(id: "link-1") { $0.withHidden(false) }
        let resultB = b.mutateLink(id: "link-1") { $0.withHidden(false) }

        // API failure → rollback to hidden
        if let rA = resultA {
            _ = a.mutateLink(id: "link-1") { _ in rA.original }
        }
        if let rB = resultB {
            _ = b.mutateLink(id: "link-1") { _ in rB.original }
        }

        #expect(a.graphLinksByKind["synonym"]?.first?.isHidden == true)
        #expect(b.graphLinksByKind["synonym"]?.first?.isHidden == true)
    }

    @Test func bilateralDeleteOptimisticUpdateRemovesFromBothEntries() {
        let (a, b, _, _) = makeBilateralPair()

        _ = a.mutateLink(id: "link-1") { _ in nil }
        _ = b.mutateLink(id: "link-1") { _ in nil }

        #expect(a.graphLinksByKind["synonym"] == nil)
        #expect(b.graphLinksByKind["synonym"] == nil)
    }

    @Test func bilateralDeleteRollbackReinsertsIntoBothEntriesOnAPIFailure() {
        let (a, b, _, _) = makeBilateralPair()

        let resultA = a.mutateLink(id: "link-1") { _ in nil }
        let resultB = b.mutateLink(id: "link-1") { _ in nil }

        // Rollback via insertLink
        if let rA = resultA {
            a.insertLink(rA.original, kind: rA.kind)
        }
        if let rB = resultB {
            b.insertLink(rB.original, kind: rB.kind)
        }

        #expect(a.graphLinksByKind["synonym"]?.count == 1)
        #expect(a.graphLinksByKind["synonym"]?.first?.id == "link-1")
        #expect(b.graphLinksByKind["synonym"]?.count == 1)
        #expect(b.graphLinksByKind["synonym"]?.first?.id == "link-1")
    }

    @Test func bilateralCounterpartMissingDoesNotCrashAndStillUpdatesCurrent() {
        let a = VocabularyEntry(word: "lucid", translation: "清晰", context: "ctx", bookTitle: "B")
        a.kgCardId = "card-a"
        let linkAtoB = KGCardLinkSummary(id: "link-1", cardId: "card-b", word: "vivid", kind: "synonym", label: "同義", confidence: 0.9, reason: "test")
        a.graphLinksByKind = ["synonym": [linkAtoB]]

        // b is nil / not found — only mutate a
        _ = a.mutateLink(id: "link-1") { $0.withHidden(true) }
        // No counterpart to mutate — should not crash

        #expect(a.graphLinksByKind["synonym"]?.first?.isHidden == true)
    }

    @Test func mutateLinkCleansUpEmptyGroup() {
        let entry = VocabularyEntry(word: "test", translation: "測試", context: "ctx", bookTitle: "B")
        let link1 = KGCardLinkSummary(id: "link-1", cardId: "c1", word: "alpha", kind: "synonym", label: "synonym", confidence: 0.9, reason: "test")
        let link2 = KGCardLinkSummary(id: "link-2", cardId: "c2", word: "beta", kind: "synonym", label: "synonym", confidence: 0.8, reason: "test")
        entry.graphLinksByKind = ["synonym": [link1, link2]]

        // Remove first link — group still has one
        _ = entry.mutateLink(id: "link-1") { _ in nil }
        #expect(entry.graphLinksByKind["synonym"]?.count == 1)

        // Remove second link — group should be cleaned up
        _ = entry.mutateLink(id: "link-2") { _ in nil }
        #expect(entry.graphLinksByKind["synonym"] == nil)
    }

    private func makeSnapshot(
        lookedUpWords: [String],
        clearHighlightTrigger: UUID = UUID(),
        underlineOpacity: Double = 0.22,
        showHitTestingDebug: Bool = false
    ) -> ReadiumNavigatorView.BridgeSnapshot {
        let configuration = ReaderViewConfiguration(
            paperColor: AppColors.paperSepia,
            epubPreferences: ReaderSettings.shared.epubPreferences,
            underlineOpacity: underlineOpacity,
            showHitTestingDebug: showHitTestingDebug,
            swiftUIColorScheme: .light,
            translationPanelMode: .glass
        )

        return .init(
            lookedUpWords: lookedUpWords,
            bookUniqueWords: Set(lookedUpWords),
            viewConfiguration: configuration,
            clearHighlightTrigger: clearHighlightTrigger,
            removeWordTrigger: nil,
            navigateToLocator: nil,
            isInteractionBlocked: false
        )
    }
}
