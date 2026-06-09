//
//  KGUserConfigReviewModeDecodeTests.swift
//  Books & Vocab Tests
//
//  Phase A3: KGUserConfig 後端契約 — review_mode 欄位 JSON decode + 向後相容。
//  wire format 為後端 snake_case(custom_*);對標 KGUserConfigReviewClockDecodeTests。
//

import Foundation
import Testing
@testable import BooksBrowser

struct KGUserConfigReviewModeDecodeTests {

    @Test func decodes_review_mode_custom() throws {
        let json = Data(#"{"review_mode":{"mode":"custom","custom_initial_interval_hours":10.0,"custom_remembered_multiplier":2.2,"custom_forgot_multiplier":0.4,"custom_minimum_interval_hours":5.0,"custom_maximum_interval_hours":2000.0,"updated_at":1717668000.0}}"#.utf8)
        let config = try JSONDecoder().decode(KGUserConfig.self, from: json)
        #expect(config.review_mode?.mode == "custom")
        #expect(config.review_mode?.custom_initial_interval_hours == 10.0)
        #expect(config.review_mode?.custom_remembered_multiplier == 2.2)
        #expect(config.review_mode?.custom_maximum_interval_hours == 2000.0)
        #expect(config.review_mode?.updated_at == 1717668000.0)
    }

    @Test func decodes_review_mode_null_updated_at() throws {
        let json = Data(#"{"review_mode":{"mode":"relaxed","custom_initial_interval_hours":12.0,"custom_remembered_multiplier":1.9,"custom_forgot_multiplier":0.45,"custom_minimum_interval_hours":6.0,"custom_maximum_interval_hours":1440.0,"updated_at":null}}"#.utf8)
        let config = try JSONDecoder().decode(KGUserConfig.self, from: json)
        #expect(config.review_mode?.mode == "relaxed")
        #expect(config.review_mode?.updated_at == nil)
    }

    @Test func backward_compat_decodes_without_review_mode() throws {
        // 舊後端 response 無 review_mode 欄位 → nil,且不影響既有 review_clock / translation。
        let json = Data(#"{"translation":{"source_lang":"en","target_lang":"ja"},"review_clock":{"is_paused":false,"paused_at":null,"updated_at":1.0}}"#.utf8)
        let config = try JSONDecoder().decode(KGUserConfig.self, from: json)
        #expect(config.review_mode == nil)
        #expect(config.review_clock?.is_paused == false)
        #expect(config.translation?.source_lang == "en")
    }
}
