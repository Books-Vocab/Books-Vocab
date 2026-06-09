//
//  KGUserConfigReviewClockDecodeTests.swift
//  Books & Vocab Tests
//
//  Phase 3: KGUserConfig 後端契約 — review_clock 欄位 JSON decode + 向後相容。
//  對標 KGServiceTests 的 wire-model decode pinning(authenticatedDecode 的 seam)。
//

import Foundation
import Testing
@testable import BooksAndVocab

struct KGUserConfigReviewClockDecodeTests {

    @Test func decodes_review_clock_paused() throws {
        let json = Data(#"{"translation":{"source_lang":"en","target_lang":"ja"},"review_clock":{"is_paused":true,"paused_at":"2026-06-06T10:00:00Z","updated_at":1717668000.0}}"#.utf8)
        let config = try JSONDecoder().decode(KGUserConfig.self, from: json)
        #expect(config.review_clock?.is_paused == true)
        #expect(config.review_clock?.paused_at == "2026-06-06T10:00:00Z")
        #expect(config.review_clock?.updated_at == 1717668000.0)
        #expect(config.translation?.target_lang == "ja")
    }

    @Test func decodes_review_clock_resumed_null_paused_at() throws {
        let json = Data(#"{"review_clock":{"is_paused":false,"paused_at":null,"updated_at":1717668100.0}}"#.utf8)
        let config = try JSONDecoder().decode(KGUserConfig.self, from: json)
        #expect(config.review_clock?.is_paused == false)
        #expect(config.review_clock?.paused_at == nil)
        #expect(config.review_clock?.updated_at == 1717668100.0)
    }

    @Test func backward_compat_decodes_without_review_clock() throws {
        let json = Data(#"{"translation":{"source_lang":"en","target_lang":"ja"}}"#.utf8)
        let config = try JSONDecoder().decode(KGUserConfig.self, from: json)
        #expect(config.review_clock == nil)
        #expect(config.translation?.source_lang == "en")
    }
}
