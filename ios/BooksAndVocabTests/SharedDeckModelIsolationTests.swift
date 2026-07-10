//
//  SharedDeckModelIsolationTests.swift
//  Books & Vocab Tests
//
//  結構性隔離契約：SharedDeck 是**獨立** @Model，公開/官方牌組絕不可滲進私人
//  Notebook 的 @Query。scout 的首要 failure mode（reuse Notebook @Model 使 public
//  deck 混進 Notebooks 列表）在型別層即被排除 —— 本測試把它釘成迴歸守衛。
//

#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct SharedDeckModelIsolationTests {

    private func makeContainer() throws -> ModelContainer {
        try ModelContainer(
            for: Notebook.self, SharedDeck.self, VocabularyEntry.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
    }

    @Test func sharedDeck_does_not_leak_into_notebook_fetch() throws {
        let container = try makeContainer()
        let ctx = container.mainContext

        let notebook = Notebook(remoteId: "nb-real", name: "My Private Notebook")
        notebook.syncStatus = 1
        ctx.insert(notebook)

        let deck = SharedDeck(remoteId: "deck_official_gre", title: "Public Official Deck")
        deck.isOfficial = true
        ctx.insert(deck)
        try ctx.save()

        // 私人 Notebook 查詢只看得到 Notebook row —— SharedDeck 不在型別範圍內。
        let notebooks = try ctx.fetch(FetchDescriptor<Notebook>())
        #expect(notebooks.count == 1)
        #expect(notebooks.first?.name == "My Private Notebook")
        #expect(!notebooks.contains { $0.name == "Public Official Deck" })

        // 反向：SharedDeck 查詢只看得到 SharedDeck row。
        let decks = try ctx.fetch(FetchDescriptor<SharedDeck>())
        #expect(decks.count == 1)
        #expect(decks.first?.title == "Public Official Deck")
        #expect(!decks.contains { $0.title == "My Private Notebook" })
    }

    @Test func sharedDeck_defaults_are_migration_safe() throws {
        // 每個 stored property 都有 default → 可只給身分欄建構（lightweight-migration 前提）。
        let container = try makeContainer()
        let ctx = container.mainContext
        let deck = SharedDeck(remoteId: "d1", title: "T")
        ctx.insert(deck)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<SharedDeck>()).first
        #expect(fetched?.isOfficial == false)
        #expect(fetched?.isSoftDeleted == false)
        #expect(fetched?.cardCount == 0)
        #expect(fetched?.tags.isEmpty == true)
    }

    @Test func notebook_provenance_defaults_nil_when_not_copied() throws {
        let container = try makeContainer()
        let ctx = container.mainContext
        let nb = Notebook(remoteId: "nb1", name: "Plain")
        ctx.insert(nb)
        try ctx.save()

        let fetched = try ctx.fetch(FetchDescriptor<Notebook>()).first
        #expect(fetched?.sourceSharedDeckId == nil)
        #expect(fetched?.sourceVersion == nil)
    }
}
#endif
