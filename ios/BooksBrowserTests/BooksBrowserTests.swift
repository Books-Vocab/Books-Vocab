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
    @Test func appObservationStoreCapsPreviewToMostRecentEntries() async throws {
        let store = AppObservationStore.shared
        store.clear()
        defer { store.clear() }

        for index in 0..<12 {
            store.record(level: .info, category: "test", message: "event=\(index)")
        }

        let preview = store.preview(limit: 5)

        #expect(preview.totalCount == 12)
        #expect(preview.entries.count == 5)
        #expect(preview.entries.first?.message == "event=7")
        #expect(preview.entries.last?.message == "event=11")
    }

    @Test func analyticsObservationPreviewRedactsSensitiveWordContent() async throws {
        let store = AppObservationStore.shared
        store.clear()
        defer { store.clear() }

        AppAnalytics.track(.translationRequested(word: "secret", type: .quick))

        let preview = store.preview(limit: 1)
        let message = try #require(preview.entries.first?.message)

        #expect(message.contains("event=translation_requested"))
        #expect(message.contains("chars=6"))
        #expect(message.contains("secret") == false)
    }

    @Test func sessionMetricsResetClearsAggregatesBetweenSnapshots() async throws {
        let metrics = SessionMetrics.shared
        metrics.reset()

        metrics.record(.syncCompleted(durationMs: 320, outcome: .success))
        metrics.record(.reviewCardSubmitted(feedback: "remembered", cardIndex: 0, totalCards: 1))
        let first = metrics.snapshot()

        #expect(first.syncCount == 1)
        #expect(first.reviewCardsTotal == 1)

        metrics.reset()
        let second = metrics.snapshot()

        #expect(second.syncCount == 0)
        #expect(second.reviewCardsTotal == 0)
    }

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
        var planner = BridgePlanner()
        let base = makeSnapshot(lookedUpWords: [])
        _ = planner.makeCommands(from: base)

        let commands = planner.makeCommands(from: makeSnapshot(lookedUpWords: ["resilient"]))

        #expect(commands.contains { command in
            if case .dom(.markNewVocabWord("resilient")) = command { return true }
            return false
        })
    }

    @Test func readerBridgePlannerClearsAndReappliesOnLargeRemoval() async throws {
        var planner = BridgePlanner()
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
        var planner = BridgePlanner()
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

    // MARK: - Notebook orphan sync defense (incident 2026-04-11)

    @MainActor
    private func makeNotebookSandbox() throws -> ModelContext {
        let container = try ModelContainer(
            for: VocabularyEntry.self, Notebook.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true)
        )
        return ModelContext(container)
    }

    /// Helper: insert a sentinel notebook so the table is not empty,
    /// satisfying `resolveNotebookId`'s cold-start guard. Without this,
    /// resolver returns the candidate verbatim and tests asserting the
    /// fallback behavior would silently pass for the wrong reason.
    @MainActor
    private func primeNotebookTable(_ ctx: ModelContext) throws {
        let primer = Notebook(remoteId: "primer-\(UUID().uuidString)", name: "Primer", color: nil)
        ctx.insert(primer)
        try ctx.save()
    }

    @Test @MainActor
    func resolveNotebookId_emptyCandidate_returnsDefault() throws {
        let ctx = try makeNotebookSandbox()
        #expect(VocabularyEntry.resolveNotebookId("", in: ctx) == "default")
    }

    @Test @MainActor
    func resolveNotebookId_defaultCandidate_returnsDefault() throws {
        let ctx = try makeNotebookSandbox()
        #expect(VocabularyEntry.resolveNotebookId("default", in: ctx) == "default")
    }

    @Test @MainActor
    func resolveNotebookId_validNotebook_returnsItself() throws {
        let ctx = try makeNotebookSandbox()
        let nb = Notebook(remoteId: "live-abc", name: "Self", color: nil)
        ctx.insert(nb)
        try ctx.save()
        #expect(VocabularyEntry.resolveNotebookId("live-abc", in: ctx) == "live-abc")
    }

    @Test @MainActor
    func resolveNotebookId_unsavedNotebook_returnsItself() throws {
        // Production race: notebook just created, not yet saved, then
        // sync triggers. Resolver must see in-memory pending insert.
        let ctx = try makeNotebookSandbox()
        let nb = Notebook(remoteId: "fresh", name: "Fresh", color: nil)
        ctx.insert(nb)
        // intentionally NO try ctx.save()
        #expect(VocabularyEntry.resolveNotebookId("fresh", in: ctx) == "fresh")
    }

    @Test @MainActor
    func resolveNotebookId_deletedNotebook_returnsDefault() throws {
        let ctx = try makeNotebookSandbox()
        // Pair a live notebook to confirm the predicate's positive arm works
        // (without this paired assertion, the test would also pass if the
        // table simply contained no `ghost` row at all, hiding a regression
        // where the `!$0.isDeleted` clause is removed).
        let live = Notebook(remoteId: "live", name: "Live", color: nil)
        ctx.insert(live)
        try ctx.save()
        #expect(VocabularyEntry.resolveNotebookId("live", in: ctx) == "live")

        let ghost = Notebook(remoteId: "ghost", name: "Ghost", color: nil)
        ctx.insert(ghost)
        ghost.isDeleted = true   // mutate after insert so it goes through persistent path
        try ctx.save()

        #expect(VocabularyEntry.resolveNotebookId("ghost", in: ctx) == "default")
    }

    @Test @MainActor
    func resolveNotebookId_unknownNotebook_returnsDefault() throws {
        let ctx = try makeNotebookSandbox()
        try primeNotebookTable(ctx)  // satisfy cold-start guard
        #expect(VocabularyEntry.resolveNotebookId("nonexistent", in: ctx) == "default")
    }

    @Test @MainActor
    func resolveNotebookId_emptyNotebookTable_returnsCandidateUnchanged() throws {
        // Cold-start guard: no notebooks fetched yet (first launch / fresh
        // login). Resolver must NOT clobber a legitimately-bound id —
        // returns it verbatim until reconcile populates the table.
        let ctx = try makeNotebookSandbox()
        #expect(VocabularyEntry.resolveNotebookId("possibly-real", in: ctx) == "possibly-real")
    }

    @Test @MainActor
    func sanitizeOutbox_emptyArray_isNoOp() throws {
        let ctx = try makeNotebookSandbox()
        SyncCoordinator.sanitizeOutbox(pendingEntries: [], modelContext: ctx)
        // Reaching here without crash is the assertion.
    }

    @Test @MainActor
    func sanitizeOutbox_orphanAdd_isReassignedToDefault() throws {
        let ctx = try makeNotebookSandbox()
        let ghost = Notebook(remoteId: "ghost", name: "Ghost", color: nil)
        ctx.insert(ghost)
        ghost.isDeleted = true
        try ctx.save()

        let entry = VocabularyEntry(
            word: "orphan",
            translation: "孤兒",
            context: "An orphan card.",
            bookTitle: "Sample"
        )
        entry.notebookId = "ghost"
        entry.restorePendingEntry()  // queue as pending add
        ctx.insert(entry)
        try ctx.save()

        // Arrange-side guard: if `restorePendingEntry()` ever stops setting
        // pending state, the test below would silently green-pass without
        // exercising sanitize. Fail fast on the precondition.
        #expect(entry.shouldUploadOnNextSync)
        #expect(entry.syncAction == .add)

        SyncCoordinator.sanitizeOutbox(pendingEntries: [entry], modelContext: ctx)

        #expect(entry.notebookId == "default")
        #expect(entry.syncAction == .add)  // still queued for upload
    }

    @Test @MainActor
    func sanitizeOutbox_orphanDelete_isHardDeletedLocally() throws {
        // Pending-delete orphan must NOT be rewritten to default — that
        // could trigger a server delete of an unrelated card with the same
        // word in default. Drop locally instead.
        let ctx = try makeNotebookSandbox()
        let ghost = Notebook(remoteId: "ghost", name: "Ghost", color: nil)
        ctx.insert(ghost)
        ghost.isDeleted = true
        try ctx.save()

        let entry = VocabularyEntry(
            word: "doomed",
            translation: "註定",
            context: "Doomed context.",
            bookTitle: "Sample"
        )
        entry.notebookId = "ghost"
        entry.markSynced()
        entry.queueDelete()
        ctx.insert(entry)
        try ctx.save()
        #expect(entry.shouldUploadOnNextSync)

        SyncCoordinator.sanitizeOutbox(pendingEntries: [entry], modelContext: ctx)

        // After sanitize, the entry should be hard-deleted from local store.
        let remaining = (try? ctx.fetch(FetchDescriptor<VocabularyEntry>())) ?? []
        #expect(remaining.contains(where: { $0.word == "doomed" }) == false)
    }

    @Test @MainActor
    func sanitizeOutbox_validPendingEntry_isUnchanged() throws {
        let ctx = try makeNotebookSandbox()
        let valid = Notebook(remoteId: "live-xyz", name: "Live", color: nil)
        ctx.insert(valid)
        try ctx.save()

        let entry = VocabularyEntry(
            word: "good",
            translation: "好",
            context: "Good context.",
            bookTitle: "Sample"
        )
        entry.notebookId = "live-xyz"
        entry.restorePendingEntry()
        ctx.insert(entry)
        try ctx.save()

        SyncCoordinator.sanitizeOutbox(pendingEntries: [entry], modelContext: ctx)

        #expect(entry.notebookId == "live-xyz")
        #expect(entry.syncState == .pending)
        #expect(entry.syncAction == .add)
    }

    @Test @MainActor
    func sanitizeOutbox_syncedOrphan_isNotTouched() throws {
        // Synced entries are out of the outbox — sanitize must skip them
        // even if their notebookId points to a deleted notebook. Mutating
        // a synced entry's notebookId would drift local from server.
        let ctx = try makeNotebookSandbox()
        let ghost = Notebook(remoteId: "ghost", name: "Ghost", color: nil)
        ctx.insert(ghost)
        ghost.isDeleted = true
        try ctx.save()

        let entry = VocabularyEntry(
            word: "settled",
            translation: "已定",
            context: "Settled context.",
            bookTitle: "Sample"
        )
        entry.notebookId = "ghost"
        entry.markSynced()
        ctx.insert(entry)
        try ctx.save()
        #expect(entry.shouldUploadOnNextSync == false)  // arrange guard

        SyncCoordinator.sanitizeOutbox(pendingEntries: [entry], modelContext: ctx)

        #expect(entry.notebookId == "ghost")  // unchanged
    }

    @Test @MainActor
    func sanitizeOutbox_alreadyDefault_isUnchanged() throws {
        let ctx = try makeNotebookSandbox()
        try primeNotebookTable(ctx)

        let entry = VocabularyEntry(
            word: "anchor",
            translation: "錨",
            context: "Anchor context.",
            bookTitle: "Sample"
        )
        // notebookId already "default"
        entry.restorePendingEntry()
        ctx.insert(entry)
        try ctx.save()

        SyncCoordinator.sanitizeOutbox(pendingEntries: [entry], modelContext: ctx)

        #expect(entry.notebookId == "default")
    }

    @Test @MainActor
    func sanitizeOutbox_emptyNotebookId_isReassignedToDefault() throws {
        // Edge case: legacy entries (or post-migration noise) could have
        // notebookId == "". Resolver short-circuits to "default", and
        // sanitize must apply that fix.
        let ctx = try makeNotebookSandbox()
        try primeNotebookTable(ctx)

        let entry = VocabularyEntry(
            word: "blank",
            translation: "空",
            context: "Blank context.",
            bookTitle: "Sample"
        )
        entry.notebookId = ""
        entry.restorePendingEntry()
        ctx.insert(entry)
        try ctx.save()

        SyncCoordinator.sanitizeOutbox(pendingEntries: [entry], modelContext: ctx)

        #expect(entry.notebookId == "default")
    }

    @Test
    func triggerPipelinesIsolated_failingNotebookDoesNotBlockOthers() async {
        // Real regression guard: calls SyncCoordinator's actual static
        // helper that startSync delegates to. If anyone refactors the
        // production loop back to fail-fast, this test will catch it.
        actor MockKG {
            var calls: [String] = []
            var failOn: Set<String> = []
            func setFailing(_ ids: [String]) { failOn = Set(ids) }
            func trigger(_ id: String) async throws {
                calls.append(id)
                if failOn.contains(id) {
                    throw URLError(.userAuthenticationRequired)  // proxy for HTTP 403
                }
            }
        }
        let mock = MockKG()
        await mock.setFailing(["4205d6bed3ed"])

        // Worst-case ordering: failing notebook first.
        let failures = await SyncCoordinator.triggerPipelinesIsolated(
            notebookIds: ["4205d6bed3ed", "default"]
        ) { nbId in
            try await mock.trigger(nbId)
        }

        let calls = await mock.calls
        #expect(calls == ["4205d6bed3ed", "default"])  // BOTH called
        #expect(failures == ["4205d6bed3ed"])
    }

    @Test
    func triggerPipelinesIsolated_allSuccess_returnsEmptyFailures() async {
        actor MockKG {
            var calls: [String] = []
            func trigger(_ id: String) async { calls.append(id) }
        }
        let mock = MockKG()
        let failures = await SyncCoordinator.triggerPipelinesIsolated(
            notebookIds: ["default"]
        ) { nbId in
            await mock.trigger(nbId)
        }
        #expect(failures.isEmpty)
        let calls = await mock.calls
        #expect(calls == ["default"])
    }

    @Test
    func triggerPipelinesIsolated_allFail_returnsAllFailures() async {
        let failures = await SyncCoordinator.triggerPipelinesIsolated(
            notebookIds: ["a", "b", "c"]
        ) { _ in
            throw URLError(.notConnectedToInternet)
        }
        #expect(failures == ["a", "b", "c"])
    }

    @Test @MainActor
    func sanitizeOutbox_tombstonedOrphanDelete_isExcludedFromDownstreamFilters() throws {
        // Regression guard for the tombstone-defense fix in startSync's
        // deletes/adds filters. After sanitize hard-deletes an orphan-delete
        // entry, that entry's PersistentModel.isDeleted becomes true. The
        // caller's [VocabularyEntry] snapshot still references it. Filters
        // that build the upload batches MUST exclude tombstones.
        let ctx = try makeNotebookSandbox()
        let ghost = Notebook(remoteId: "ghost", name: "Ghost", color: nil)
        ctx.insert(ghost)
        ghost.isDeleted = true
        let live = Notebook(remoteId: "live", name: "Live", color: nil)
        ctx.insert(live)
        try ctx.save()

        // Mix: one orphan delete (will be tombstoned by sanitize), one valid add
        let orphanDelete = VocabularyEntry(
            word: "doomed", translation: "註定", context: "ctx", bookTitle: "B"
        )
        orphanDelete.notebookId = "ghost"
        orphanDelete.markSynced()
        orphanDelete.queueDelete()
        ctx.insert(orphanDelete)

        let validAdd = VocabularyEntry(
            word: "alive", translation: "活著", context: "ctx", bookTitle: "B"
        )
        validAdd.notebookId = "live"
        validAdd.restorePendingEntry()
        ctx.insert(validAdd)
        try ctx.save()

        let snapshot = [orphanDelete, validAdd]
        SyncCoordinator.sanitizeOutbox(pendingEntries: snapshot, modelContext: ctx)

        // Mirror the production filters from startSync. The orphanDelete is
        // tombstoned and MUST be excluded; validAdd survives.
        let deletes = snapshot.filter { !$0.isDeleted && $0.syncAction == .delete && $0.shouldUploadOnNextSync }
        let adds = snapshot.filter { !$0.isDeleted && $0.syncAction == .add && $0.shouldUploadOnNextSync }

        #expect(deletes.isEmpty)  // tombstone defense
        #expect(adds.count == 1)
        #expect(adds.first?.word == "alive")
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
        // ReaderViewConfiguration is built via ReaderSettings.viewConfiguration(systemColorScheme:);
        // post-refactor `translationPanelMode` was removed from the struct.
        let baseConfig = ReaderSettings.shared.viewConfiguration(systemColorScheme: .light)
        let configuration = ReaderViewConfiguration(
            paperColor: AppColors.paperSepia,
            epubPreferences: baseConfig.epubPreferences,
            underlineOpacity: underlineOpacity,
            showHitTestingDebug: showHitTestingDebug,
            swiftUIColorScheme: .light
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
