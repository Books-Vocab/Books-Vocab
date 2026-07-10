//
//  SharedDeckWireDecodeTests.swift
//  Books & Vocab Tests
//
//  Explore 共享牌組 wire 契約 —— lenient decode + forward-compat + 零 SRS 洩漏。
//  對標 KGUserConfigAutoLinkDecodeTests 的 wire-model decode pinning。
//

import Foundation
import Testing
@testable import BooksAndVocab

struct SharedDeckWireDecodeTests {

    // MARK: - Summary

    @Test func decodes_full_summary() throws {
        let json = Data(#"""
        {"deckId":"deck_official_gre","title":"GRE 高頻","color":"#AABBCC",
         "coverPattern":"noise","authorLabel":"KG 官方","isOfficial":true,
         "cardCount":618,"downloadCount":42,"ratingAvg":4.5,"ratingCount":10,
         "languagePair":"en-zh","category":"exam","tags":["gre","exam"],
         "updatedAt":"2026-07-01T00:00:00Z"}
        """#.utf8)
        let s = try JSONDecoder().decode(SharedDeckSummary.self, from: json)
        #expect(s.deckId == "deck_official_gre")
        #expect(s.title == "GRE 高頻")
        #expect(s.isOfficial == true)
        #expect(s.cardCount == 618)
        #expect(s.downloadCount == 42)
        #expect(s.ratingAvg == 4.5)
        #expect(s.ratingCount == 10)
        #expect(s.languagePair == "en-zh")
        #expect(s.category == "exam")
        #expect(s.tags == ["gre", "exam"])
    }

    @Test func lenient_summary_missing_non_identity_fields_degrade_to_defaults() throws {
        // 只有身分欄 → 其餘降級安全預設，不炸。
        let json = Data(#"{"deckId":"d1","title":"Minimal"}"#.utf8)
        let s = try JSONDecoder().decode(SharedDeckSummary.self, from: json)
        #expect(s.isOfficial == false)
        #expect(s.cardCount == 0)
        #expect(s.downloadCount == 0)
        #expect(s.ratingCount == 0)
        #expect(s.ratingAvg == nil)
        #expect(s.tags.isEmpty)
        #expect(s.category == nil)
    }

    @Test func forward_compat_summary_ignores_unknown_keys() throws {
        // 後端加了未來欄位（visibility / shareToken…）→ 舊 app decode 不炸。
        let json = Data(#"""
        {"deckId":"d1","title":"T","visibility":"public","shareToken":"xyz",
         "future_field":{"nested":true},"reportCount":3}
        """#.utf8)
        let s = try JSONDecoder().decode(SharedDeckSummary.self, from: json)
        #expect(s.deckId == "d1")
        #expect(s.title == "T")
    }

    @Test func summary_missing_identity_throws() throws {
        // deckId 缺 → 必填，decode 應拋（身分欄不可降級）。
        let json = Data(#"{"title":"NoId"}"#.utf8)
        #expect(throws: (any Error).self) {
            try JSONDecoder().decode(SharedDeckSummary.self, from: json)
        }
    }

    // MARK: - DeckCard (零 SRS)

    @Test func decodes_deck_card_content_plane() throws {
        let json = Data(#"""
        {"id":"c1","content":"ephemeral","pos":"adj","meaning":"短暫的",
         "examples":["an ephemeral moment"],"collocations":["ephemeral beauty"],
         "note":"formal","difficulty":0.7,"mode":"translation",
         "rootForm":"ephemeral","inflections":["ephemerally"]}
        """#.utf8)
        let card = try JSONDecoder().decode(SharedDeckCard.self, from: json)
        #expect(card.id == "c1")
        #expect(card.content == "ephemeral")
        #expect(card.meaning == "短暫的")
        #expect(card.examples == ["an ephemeral moment"])
        #expect(card.mode == "translation")
    }

    @Test func deck_card_ignores_srs_fields_if_server_leaks_them() throws {
        // 即便後端誤帶 SRS 欄位，DeckCard 型別層沒有這些屬性 → 天然忽略、不洩漏。
        let json = Data(#"""
        {"id":"c1","content":"w","meaning":"m","reviewIntervalHours":12.0,
         "nextReviewAt":"2026-07-02T00:00:00Z","reviewCount":5,"lapseCount":1,
         "reviewStreak":3,"lastReviewFeedback":1,"lastReviewedAt":"2026-07-01T00:00:00Z"}
        """#.utf8)
        let card = try JSONDecoder().decode(SharedDeckCard.self, from: json)
        #expect(card.id == "c1")
        #expect(card.content == "w")
        // Structural proof: the Mirror over DeckCard carries zero SRS-named children.
        let names = Set(Mirror(reflecting: card).children.compactMap(\.label))
        let srs = ["reviewIntervalHours", "nextReviewAt", "lastReviewedAt", "reviewCount",
                   "lapseCount", "reviewStreak", "lastReviewFeedback"]
        for field in srs {
            #expect(!names.contains(field), "DeckCard must not carry SRS field \(field)")
        }
    }

    @Test func lenient_deck_card_missing_arrays_degrade_to_empty() throws {
        let json = Data(#"{"id":"c1","content":"w","meaning":"m"}"#.utf8)
        let card = try JSONDecoder().decode(SharedDeckCard.self, from: json)
        #expect(card.examples.isEmpty)
        #expect(card.collocations.isEmpty)
        #expect(card.inflections.isEmpty)
        #expect(card.mode == "")
    }

    // MARK: - Responses

    @Test func decodes_list_response_with_cursor() throws {
        let json = Data(#"""
        {"decks":[{"deckId":"d1","title":"A"},{"deckId":"d2","title":"B"}],
         "nextCursor":"opaque-cursor-token"}
        """#.utf8)
        let resp = try JSONDecoder().decode(SharedDeckListResponse.self, from: json)
        #expect(resp.decks.count == 2)
        #expect(resp.nextCursor == "opaque-cursor-token")
    }

    @Test func decodes_list_response_null_cursor() throws {
        let json = Data(#"{"decks":[],"nextCursor":null}"#.utf8)
        let resp = try JSONDecoder().decode(SharedDeckListResponse.self, from: json)
        #expect(resp.decks.isEmpty)
        #expect(resp.nextCursor == nil)
    }

    @Test func decodes_detail_flat_summary_plus_sample_cards() throws {
        // detail = summary 欄位 flat + sampleCards + cardsCursor 同層。
        let json = Data(#"""
        {"deckId":"d1","title":"Deck","isOfficial":true,"cardCount":100,
         "sampleCards":[{"id":"c1","content":"w1","meaning":"m1"},
                        {"id":"c2","content":"w2","meaning":"m2"}],
         "cardsCursor":"next-cards"}
        """#.utf8)
        let detail = try JSONDecoder().decode(SharedDeckDetail.self, from: json)
        #expect(detail.summary.deckId == "d1")
        #expect(detail.summary.cardCount == 100)
        #expect(detail.summary.isOfficial == true)
        #expect(detail.sampleCards.count == 2)
        #expect(detail.cardsCursor == "next-cards")
    }

    @Test func decodes_detail_without_sample_cards() throws {
        let json = Data(#"{"deckId":"d1","title":"Deck"}"#.utf8)
        let detail = try JSONDecoder().decode(SharedDeckDetail.self, from: json)
        #expect(detail.sampleCards.isEmpty)
        #expect(detail.cardsCursor == nil)
    }

    @Test func decodes_cards_response() throws {
        let json = Data(#"""
        {"cards":[{"id":"c1","content":"w","meaning":"m"}],"nextCursor":"cur"}
        """#.utf8)
        let resp = try JSONDecoder().decode(SharedDeckCardsResponse.self, from: json)
        #expect(resp.cards.count == 1)
        #expect(resp.nextCursor == "cur")
    }

    // MARK: - Notebook provenance wire

    @Test func decodes_notebook_provenance_fields() throws {
        let json = Data(#"""
        {"id":"nb1","name":"Copied","color":null,"coverPattern":null,"sortOrder":0,
         "isDefault":false,"isDeleted":false,"cardCount":10,"updatedAt":null,
         "sourceSharedDeckId":"deck_official_gre","sourceVersion":2}
        """#.utf8)
        let nb = try JSONDecoder().decode(KGNotebook.self, from: json)
        #expect(nb.sourceSharedDeckId == "deck_official_gre")
        #expect(nb.sourceVersion == 2)
    }

    @Test func backward_compat_notebook_without_provenance() throws {
        // 舊後端無 provenance 欄位 → nil，不炸。
        let json = Data(#"""
        {"id":"nb1","name":"Plain","color":null,"coverPattern":null,"sortOrder":0,
         "isDefault":false,"isDeleted":false,"cardCount":0,"updatedAt":null}
        """#.utf8)
        let nb = try JSONDecoder().decode(KGNotebook.self, from: json)
        #expect(nb.sourceSharedDeckId == nil)
        #expect(nb.sourceVersion == nil)
    }
}
