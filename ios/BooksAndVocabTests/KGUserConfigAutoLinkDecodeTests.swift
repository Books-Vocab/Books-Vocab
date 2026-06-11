//
//  KGUserConfigAutoLinkDecodeTests.swift
//  Books & Vocab Tests
//
//  KGUserConfig 後端契約 — auto_link 欄位 JSON decode + 向後相容。
//  對標 KGUserConfigReviewClockDecodeTests 的 wire-model decode pinning。
//

import Foundation
import Testing
@testable import BooksAndVocab

struct KGUserConfigAutoLinkDecodeTests {

    @Test func decodes_auto_link_disabled() throws {
        let json = Data(#"{"auto_link":{"enabled":false,"updated_at":1717668000.0}}"#.utf8)
        let config = try JSONDecoder().decode(KGUserConfig.self, from: json)
        #expect(config.auto_link?.enabled == false)
        #expect(config.auto_link?.updated_at == 1717668000.0)
    }

    @Test func decodes_auto_link_enabled_null_updated_at() throws {
        let json = Data(#"{"auto_link":{"enabled":true,"updated_at":null}}"#.utf8)
        let config = try JSONDecoder().decode(KGUserConfig.self, from: json)
        #expect(config.auto_link?.enabled == true)
        #expect(config.auto_link?.updated_at == nil)
    }

    @Test func backward_compat_decodes_without_auto_link() throws {
        // 舊後端回應無 auto_link 欄位 → decode 不炸、欄位為 nil。
        let json = Data(#"{"translation":{"source_lang":"en","target_lang":"ja"}}"#.utf8)
        let config = try JSONDecoder().decode(KGUserConfig.self, from: json)
        #expect(config.auto_link == nil)
        #expect(config.translation?.source_lang == "en")
    }
}
