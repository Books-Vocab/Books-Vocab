//
//  VocabPullChangeDetectionTests.swift
//  Books & Vocab Tests
//
//  Pins the "did this sync actually change anything" contract.
//
//  The bug being guarded: every visit to a notebook ran `.task` →
//  `loadInitialData` → pull → and unconditionally announced「單字庫已更新」,
//  regardless of whether the merge touched a single row. A confirmation that
//  fires whether or not anything happened carries no information, so users
//  learn to ignore it — and a real update becomes indistinguishable from a
//  no-op sync.
//
//  Two halves are pinned here:
//   1. `BackgroundSyncActor.contentDiffers` / the merge counters — what counts
//      as a change (and, critically, what does NOT: review state).
//   2. `KGVocabCoordinator.successMessage` — when a change is worth saying out
//      loud, split by who triggered the sync.
//

#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct VocabPullChangeDetectionTests {

    // MARK: - Helpers

    private func makeContainer() throws -> ModelContainer {
        let schema = Schema([
            VocabularyEntry.self,
            ReviewRecord.self,
            Notebook.self,
            Book.self,
            PodcastSeries.self,
            PodcastEpisode.self,
            PodcastProgress.self
        ])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        return try ModelContainer(for: schema, configurations: [config])
    }

    /// Decode through the same plain `JSONDecoder` path production uses.
    private func makeCard(
        id: String = "c1",
        content: String,
        meaning: String = "meaning",
        pos: String? = nil,
        note: String? = nil,
        examples: [String] = ["an example"],
        isArchived: Bool = false,
        reviewFragment: String = ""
    ) throws -> KGCard {
        func quoted(_ s: String?) -> String { s.map { "\"\($0)\"" } ?? "null" }
        let json = """
        {"id":"\(id)","content":"\(content)","meaning":"\(meaning)",
         "pos":\(quoted(pos)),"difficulty":null,"difficultyTier":null,"note":\(quoted(note)),
         "collocations":[],"examples":[\(examples.map { "\"\($0)\"" }.joined(separator: ","))],
         "mode":"recognition","isDeleted":false,"isArchived":\(isArchived),
         "notebookId":"default"\(reviewFragment)}
        """.data(using: .utf8)!
        return try JSONDecoder().decode(KGCard.self, from: json)
    }

    /// A local entry that already matches `makeCard(content: "deft", meaning: "靈巧的")`
    /// **and is already synced**.
    ///
    /// The synced part matters: a freshly constructed `VocabularyEntry` is
    /// `syncStatus = 0` (pending), and `contentDiffers` reports that as a change
    /// on its own — the merge's `markSynced()` would make the row appear in the
    /// list. A test meaning to probe one content field has to pin that axis
    /// first, or it passes on the wrong cause.
    private func makeSyncedEntry(explanation: String? = nil) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: "deft", translation: "靈巧的", context: "an example",
            explanation: explanation, partOfSpeech: nil,
            bookTitle: "Knowledge Graph", chapterTitle: nil
        )
        entry.reviewExamples = ["an example"]
        entry.markSynced()
        return entry
    }

    // MARK: - merge counters

    @Test func firstPull_countsEveryCardAsInserted() async throws {
        let container = try makeContainer()
        let actor = BackgroundSyncActor(modelContainer: container)

        let result = try await actor.pullCardsToLocal(
            fetchedCards: [
                try makeCard(id: "c1", content: "lascivious"),
                try makeCard(id: "c2", content: "forestall")
            ],
            isIncremental: true,
            progress: { _, _, _ in }
        )

        #expect(result.inserted == 2)
        #expect(result.updated == 0)
        #expect(result.deleted == 0)
        #expect(result.hasChanges)
    }

    /// The core regression: pulling the *same* payload twice must report the
    /// second pull as a no-op. This is the shape of nearly every real refresh —
    /// an incremental sync that hands back cards the device already has.
    @Test func repeatedPull_ofIdenticalPayload_reportsNoChanges() async throws {
        let container = try makeContainer()
        let actor = BackgroundSyncActor(modelContainer: container)
        let cards = [
            try makeCard(id: "c1", content: "lascivious", meaning: "色情的", pos: "adj."),
            try makeCard(id: "c2", content: "forestall", meaning: "預先阻止", pos: "v.")
        ]

        _ = try await actor.pullCardsToLocal(
            fetchedCards: cards, isIncremental: true, progress: { _, _, _ in }
        )
        let second = try await actor.pullCardsToLocal(
            fetchedCards: cards, isIncremental: true, progress: { _, _, _ in }
        )

        #expect(second.inserted == 0)
        #expect(second.updated == 0)
        #expect(second.deleted == 0)
        #expect(!second.hasChanges)
    }

    @Test func pull_withChangedMeaning_countsAsUpdated() async throws {
        let container = try makeContainer()
        let actor = BackgroundSyncActor(modelContainer: container)

        _ = try await actor.pullCardsToLocal(
            fetchedCards: [try makeCard(id: "c1", content: "deft", meaning: "靈巧的")],
            isIncremental: true, progress: { _, _, _ in }
        )
        let second = try await actor.pullCardsToLocal(
            fetchedCards: [try makeCard(id: "c1", content: "deft", meaning: "熟練的")],
            isIncremental: true, progress: { _, _, _ in }
        )

        #expect(second.updated == 1)
        #expect(second.inserted == 0)
        #expect(second.hasChanges)
    }

    @Test func pull_withRemoteSoftDelete_countsAsDeleted() async throws {
        let container = try makeContainer()
        let actor = BackgroundSyncActor(modelContainer: container)
        _ = try await actor.pullCardsToLocal(
            fetchedCards: [try makeCard(id: "c1", content: "obsolete")],
            isIncremental: true, progress: { _, _, _ in }
        )

        let tombstone = try JSONDecoder().decode(KGCard.self, from: """
        {"id":"c1","content":"obsolete","meaning":"meaning","pos":null,"difficulty":null,
         "difficultyTier":null,"note":null,"collocations":[],"examples":[],"mode":"recognition",
         "isDeleted":true,"notebookId":"default"}
        """.data(using: .utf8)!)

        let second = try await actor.pullCardsToLocal(
            fetchedCards: [tombstone], isIncremental: true, progress: { _, _, _ in }
        )

        #expect(second.deleted == 1)
        #expect(second.hasChanges)
    }

    // MARK: - contentDiffers: review state is NOT content

    /// Review state round-trips through the server on every single review: this
    /// device pushes it, the next incremental pull hands it straight back. If
    /// that counted as "the vocabulary changed", the banner would fire after
    /// every review session — the same cheap-signal failure this work removes.
    @Test func contentDiffers_ignoresReviewStateOnlyChange() throws {
        let entry = makeSyncedEntry()
        entry.reviewCount = 3
        entry.lastReviewedAt = Date(timeIntervalSince1970: 1_000)

        let reviewed = try makeCard(
            content: "deft", meaning: "靈巧的",
            reviewFragment: #","reviewCount":99,"lastReviewedAt":"2026-08-05T04:14:13Z","reviewStreak":7"#
        )

        #expect(!BackgroundSyncActor.contentDiffers(card: reviewed, from: entry))
    }

    @Test func contentDiffers_detectsArchiveFlip() throws {
        let entry = makeSyncedEntry()

        // Guard the guard: assert the entry is otherwise a match, so the `true`
        // below can only come from the archive flip. Without this, the
        // not-yet-synced rule would satisfy the assertion first and the test
        // would pass while proving nothing about `isArchived`.
        let unchanged = try makeCard(content: "deft", meaning: "靈巧的")
        #expect(!BackgroundSyncActor.contentDiffers(card: unchanged, from: entry))

        let archived = try makeCard(content: "deft", meaning: "靈巧的", isArchived: true)
        #expect(BackgroundSyncActor.contentDiffers(card: archived, from: entry))
    }

    /// The merge's final act is `markSynced()`. For an entry that was still
    /// `pending`/`failed`, that flip is what makes the row appear in the list at
    /// all (`shouldAppearInKnowledgeList` requires `isSynced`) — so it counts as
    /// a change even when every content field already matched.
    @Test func contentDiffers_detectsPendingEntryBecomingSynced() throws {
        let entry = VocabularyEntry(
            word: "deft", translation: "靈巧的", context: "an example",
            explanation: nil, partOfSpeech: nil, bookTitle: "Knowledge Graph", chapterTitle: nil
        )
        entry.reviewExamples = ["an example"]
        entry.restorePendingEntry()
        #expect(!entry.isSynced)

        let identical = try makeCard(content: "deft", meaning: "靈巧的")
        #expect(BackgroundSyncActor.contentDiffers(card: identical, from: entry))

        entry.markSynced()
        #expect(!BackgroundSyncActor.contentDiffers(card: identical, from: entry))
    }

    /// Orphan cleanup only runs on a full sync whose safety valve did not trip.
    /// A blocked cleanup deleted nothing, so it must report nothing deleted —
    /// otherwise the UI announces an update for rows that are all still there.
    @Test func fullSync_blockedOrphanCleanup_reportsNoDeletions() async throws {
        let container = try makeContainer()
        let actor = BackgroundSyncActor(modelContainer: container)

        // Seed 10 synced entries, then full-sync with a single card: the server
        // returned <30% of local, so the mass-deletion valve blocks cleanup.
        let seeded = try (0..<10).map { try makeCard(id: "c\($0)", content: "word\($0)") }
        _ = try await actor.pullCardsToLocal(
            fetchedCards: seeded, isIncremental: false, progress: { _, _, _ in }
        )

        let result = try await actor.pullCardsToLocal(
            fetchedCards: [try makeCard(id: "c0", content: "word0")],
            isIncremental: false,
            progress: { _, _, _ in }
        )

        #expect(result.orphanCleanupBlocked)
        #expect(result.deleted == 0)
    }

    @Test func contentDiffers_detectsExplanationChange() throws {
        let entry = makeSyncedEntry(explanation: "old note")

        let sameNote = try makeCard(content: "deft", meaning: "靈巧的", note: "old note")
        #expect(!BackgroundSyncActor.contentDiffers(card: sameNote, from: entry))

        let renoted = try makeCard(content: "deft", meaning: "靈巧的", note: "new note")
        #expect(BackgroundSyncActor.contentDiffers(card: renoted, from: entry))
    }

    // MARK: - successMessage policy

    @Test func successMessage_automaticPull_withNoChanges_staysSilent() {
        let message = KGVocabCoordinator.successMessage(
            for: .unchanged, trigger: .automatic
        )
        #expect(message == nil)
    }

    @Test func successMessage_automaticPull_withChanges_announcesUpdate() {
        let message = KGVocabCoordinator.successMessage(
            for: KGPullOutcome(pipelinePending: false, inserted: 3), trigger: .automatic
        )
        #expect(message == L10n.string("單字庫已更新"))
    }

    /// A user who pulled to refresh must always get an answer — silence reads as
    /// "the gesture didn't register". Only the *automatic* pull stays quiet.
    @Test func successMessage_explicitPull_withNoChanges_confirmsUpToDate() {
        let message = KGVocabCoordinator.successMessage(
            for: .unchanged, trigger: .explicit
        )
        #expect(message == L10n.string("單字庫已是最新"))
        #expect(message != L10n.string("單字庫已更新"))
    }

    @Test func successMessage_explicitPull_withChanges_announcesUpdate() {
        let message = KGVocabCoordinator.successMessage(
            for: KGPullOutcome(pipelinePending: false, deleted: 1), trigger: .explicit
        )
        #expect(message == L10n.string("單字庫已更新"))
    }

    /// `pipelinePending` is about the *server* still working, not about local
    /// data changing — it must not fake a change on its own.
    @Test func successMessage_pipelinePendingAlone_isNotAChange() {
        let message = KGVocabCoordinator.successMessage(
            for: KGPullOutcome(pipelinePending: true), trigger: .automatic
        )
        #expect(message == nil)
    }

    // MARK: - localization

    /// These four banner strings shipped with no entry in ANY .lproj. `L10n`'s
    /// three-tier lookup then fell through to "the key itself" — so an
    /// English-locale device rendered the raw Chinese key inside an otherwise
    /// English screen, which is exactly what the original bug report screenshot
    /// shows. Asserting against the **en** bundle directly is the only check
    /// that fails for the shipped state: a zh-Hant test device would have been
    /// happy either way.
    @Test func bannerSuccessStrings_haveEnglishTranslations() throws {
        let path = try #require(Bundle.main.path(forResource: "en", ofType: "lproj"))
        let enBundle = try #require(Bundle(path: path))

        for key in ["單字庫已更新", "單字庫已是最新", "待刪除項目已同步", "封存已同步"] {
            let english = enBundle.localizedString(
                forKey: key, value: "**missing**", table: "Localizable"
            )
            #expect(english != "**missing**", "no en.lproj entry for \(key)")
            #expect(english != key, "en.lproj entry for \(key) is still the Chinese key")
        }
    }
}
#endif
