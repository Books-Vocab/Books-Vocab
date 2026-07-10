//
//  SharedDeckCopyPullTests.swift
//  Books & Vocab Tests
//
//  Explore 複製後針對性增量 pull（2c-2）—— merge seam 的兩條 load-bearing 不變式：
//  (1) 複製卡以 SYNCED 落地目標 notebook、即時可複習；
//  (2) notebook-scoped merge 不觸 orphan cleanup（不刪其他 notebook 的卡）、
//      不動全域 incremental boundary（否則下次全量增量 sync 會漏其他 notebook 的變更）。
//
//  註：KGService 無 URLSession 注入 seam（見 KGServiceTests 說明），故 pullCopiedDeck
//  端到端無法單測；此處測 card-injected 的 `mergeNotebookScopedCards` 純 seam。
//

#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct SharedDeckCopyPullTests {

    private func makeContainer() throws -> ModelContainer {
        let schema = Schema([
            VocabularyEntry.self, ReviewRecord.self, Notebook.self,
            Book.self, PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self
        ])
        return try ModelContainer(
            for: schema,
            configurations: [ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)]
        )
    }

    /// A copied server card as it arrives on sync-down (camelCase, notebook-scoped).
    private func card(id: String, content: String, notebookId: String) throws -> KGCard {
        let json = """
        {"id":"\(id)","content":"\(content)","meaning":"m-\(content)",
         "pos":null,"difficulty":null,"difficultyTier":null,"note":null,
         "collocations":[],"examples":[],"mode":"recognition",
         "isDeleted":false,"notebookId":"\(notebookId)"}
        """.data(using: .utf8)!
        return try JSONDecoder().decode(KGCard.self, from: json)
    }

    private func entries(_ container: ModelContainer) throws -> [VocabularyEntry] {
        try container.mainContext.fetch(FetchDescriptor<VocabularyEntry>())
    }

    // MARK: - Copied cards land as SYNCED in the target notebook

    @Test func copiedCards_land_as_synced_in_target_notebook() async throws {
        let container = try makeContainer()
        let cards = [
            try card(id: "cc1", content: "ephemeral", notebookId: "nb-copied"),
            try card(id: "cc2", content: "serendipity", notebookId: "nb-copied"),
        ]

        try await KGService.mergeNotebookScopedCards(cards, notebookId: "nb-copied", container: container)

        let all = try entries(container)
        #expect(all.count == 2)
        for e in all {
            #expect(e.notebookId == "nb-copied")
            #expect(e.syncStatus == 1, "copied cards must land as synced so they are immediately reviewable")
            #expect(e.shouldAppearInKnowledgeList)   // synced, not deleted, not archived
        }
        #expect(Set(all.map(\.word)) == ["ephemeral", "serendipity"])
    }

    // MARK: - Notebook-scoped merge must NOT reap other notebooks' cards

    @Test func merge_does_not_delete_other_notebooks_cards() async throws {
        let container = try makeContainer()
        // Pre-existing synced card in a DIFFERENT notebook.
        let other = VocabularyEntry(word: "extant", translation: "existing", context: "", bookTitle: "Other Book")
        other.notebookId = "nb-other"
        other.kgCardId = "other-1"
        other.markSynced()
        container.mainContext.insert(other)
        try container.mainContext.save()

        // Pull ONLY the copied notebook's cards.
        try await KGService.mergeNotebookScopedCards(
            [try card(id: "cc1", content: "ephemeral", notebookId: "nb-copied")],
            notebookId: "nb-copied", container: container
        )

        let all = try entries(container)
        // The other notebook's synced card survives (orphan cleanup skipped),
        // and the copied card is added → 2 total.
        #expect(all.contains { $0.word == "extant" && $0.notebookId == "nb-other" },
                "a notebook-scoped copy pull must NOT reap synced cards in other notebooks")
        #expect(all.contains { $0.word == "ephemeral" && $0.notebookId == "nb-copied" })
        #expect(all.count == 2)
    }

    // MARK: - The copy pull is boundary-neutral

    @Test func merge_does_not_touch_global_incremental_boundary() async throws {
        let container = try makeContainer()
        let defaults = UserDefaults.standard
        let key = KGService.SyncKeys.incrementalBoundary
        let sentinel = 1_700_000_000.0   // a known prior boundary
        defaults.set(sentinel, forKey: key)
        defer { defaults.removeObject(forKey: key) }

        try await KGService.mergeNotebookScopedCards(
            [try card(id: "cc1", content: "ephemeral", notebookId: "nb-copied")],
            notebookId: "nb-copied", container: container
        )

        // A notebook-scoped pull must leave the GLOBAL boundary exactly as it was —
        // advancing it would make the next full incremental sync skip other
        // notebooks' server-side changes since the old boundary.
        #expect(defaults.double(forKey: key) == sentinel)
    }
}
#endif
