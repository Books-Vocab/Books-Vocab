#if DEBUG && canImport(Playbook)
//
//  SharedDeckCatalogFixtures.swift
//  Books & Vocab
//
//  Deterministic seed data for the Explore catalog scenes (ExploreView /
//  SharedDeckDetailView). Seeds a **local** in-memory SharedDeck store directly —
//  NOT the ops-emitted `kg.fixture.dataset.v2` UI World. Adding a new required
//  top-level domain (`sharedDeck`) to that schema would break the ops emitter's
//  byte-equal decode（跨 ios/ 邊界，須 ops 配合）; fully UI-World-integrated
//  SharedDeck seeds are a follow-up requiring an ops emitter change.
//

import Foundation
import SwiftData

enum SharedDeckCatalogFixtures {
    struct DeckSpec {
        let remoteId: String
        let title: String
        let author: String?
        let isOfficial: Bool
        let category: String?
        let languagePair: String?
        let tags: [String]
        let cardCount: Int
        let downloadCount: Int
        let ratingAvg: Double?
        let ratingCount: Int
        let color: String?
        let coverPattern: String?
    }

    static let populated: [DeckSpec] = [
        DeckSpec(
            remoteId: "deck_official_gre_high_freq", title: "GRE 高頻核心 1200",
            author: nil, isOfficial: true, category: "exam", languagePair: "en-zh",
            tags: ["gre", "exam"], cardCount: 1200, downloadCount: 4820, ratingAvg: 4.6,
            ratingCount: 312, color: "#AFC2D3", coverPattern: "lines"
        ),
        DeckSpec(
            remoteId: "deck_official_toefl_essentials", title: "TOEFL 學術詞彙精選",
            author: nil, isOfficial: true, category: "exam", languagePair: "en-zh",
            tags: ["toefl", "academic"], cardCount: 860, downloadCount: 2145, ratingAvg: 4.4,
            ratingCount: 188, color: "#DCABA4", coverPattern: "dots"
        ),
        DeckSpec(
            remoteId: "deck_official_everyday_phrases", title: "Everyday English Phrases",
            author: nil, isOfficial: true, category: "phrase", languagePair: "en-zh",
            tags: ["daily", "conversation"], cardCount: 420, downloadCount: 6103, ratingAvg: 4.8,
            ratingCount: 540, color: "#B8C9A8", coverPattern: "waves"
        ),
        DeckSpec(
            remoteId: "deck_official_business_english", title: "商用英文書信與會議",
            author: nil, isOfficial: true, category: "language", languagePair: "en-zh",
            tags: ["business"], cardCount: 300, downloadCount: 980, ratingAvg: nil,
            ratingCount: 0, color: "#C9B8D6", coverPattern: "grid"
        ),
    ]

    /// Seed a fresh in-memory SharedDeck store with the given specs (sortOrder by
    /// declaration order, mirroring the server's recency-sorted browse response).
    /// `@MainActor`: touches `container.mainContext`（MainActor-isolated）；scene
    /// 為 View（隱式 MainActor）故 init 可呼叫。
    @MainActor
    static func makeContainer(specs: [DeckSpec]) -> ModelContainer {
        do {
            let container = try ModelContainer(
                for: SharedDeck.self,
                configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
            )
            for (index, spec) in specs.enumerated() {
                let deck = SharedDeck(remoteId: spec.remoteId, title: spec.title)
                deck.authorLabel = spec.author
                deck.isOfficial = spec.isOfficial
                deck.category = spec.category
                deck.languagePair = spec.languagePair
                deck.tags = spec.tags
                deck.cardCount = spec.cardCount
                deck.downloadCount = spec.downloadCount
                deck.ratingAvg = spec.ratingAvg
                deck.ratingCount = spec.ratingCount
                deck.color = spec.color
                deck.coverPattern = spec.coverPattern
                deck.updatedAt = Date(timeIntervalSince1970: 1_782_000_000 - Double(index) * 86_400)
                deck.sortOrder = index
                container.mainContext.insert(deck)
            }
            try container.mainContext.save()
            return container
        } catch {
            preconditionFailure("Failed to seed SharedDeck catalog fixture: \(error)")
        }
    }

    /// Deterministic sample cards for the detail preview（content plane only, 零 SRS）。
    static func sampleCards() -> [SharedDeckCard] {
        [
            SharedDeckCard(
                id: "card_ephemeral", content: "ephemeral", meaning: "短暫的；曇花一現的",
                pos: "adj.", examples: ["Fame in the digital age is often ephemeral."],
                mode: "translation", rootForm: "ephemeral"
            ),
            SharedDeckCard(
                id: "card_ubiquitous", content: "ubiquitous", meaning: "無所不在的",
                pos: "adj.", examples: ["Smartphones have become ubiquitous."],
                mode: "translation"
            ),
            SharedDeckCard(
                id: "card_meticulous", content: "meticulous", meaning: "一絲不苟的；謹慎的",
                pos: "adj.", examples: ["She kept meticulous records."], mode: "translation"
            ),
            SharedDeckCard(
                id: "card_pragmatic", content: "pragmatic", meaning: "務實的",
                pos: "adj.", examples: [], mode: "translation"
            ),
        ]
    }
}
#endif
