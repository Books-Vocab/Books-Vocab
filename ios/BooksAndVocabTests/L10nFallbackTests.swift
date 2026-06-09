//
//  L10nFallbackTests.swift
//  Books & Vocab Tests
//
//  Verifies L10n three-tier fallback (current locale → en → key) and plural format wiring.
//

import Foundation
import Testing
@testable import BooksAndVocab

// .serialized: tests mutate AppLanguageStore.shared singleton.
@Suite(.serialized)
@MainActor
struct L10nFallbackTests {

    // Test 1: 當 ja bundle 缺鍵時應回 en 翻譯,而非中文 key 原文。
    // 選用 "初始間隔":en bundle = "Initial Interval",ja/ko bundle 缺鍵。
    // (driver: `comm -23 en-keys ja-keys` 確認 ja 不含此 key)
    @Test func test_missing_key_falls_back_to_english_not_chinese_key() async throws {
        let key = "初始間隔"
        let store = AppLanguageStore.shared
        store.setLanguage(.japanese)
        defer { store.setLanguage(.system) }

        let result = L10n.string(key)

        #expect(result != key, "fallback to chinese key means UI leak in non-CJK locale; got \(result)")
        let hasChinese = result.unicodeScalars.contains { (0x4E00...0x9FFF).contains($0.value) }
        #expect(hasChinese == false, "expected English fallback, got: \(result)")
        #expect(result == "Initial Interval")
    }

    // Test 2: 所有 locale 都缺鍵時,回 key 本身。
    @Test func test_missing_in_all_locales_returns_key_itself() async throws {
        let key = "__definitely_missing_key_xyz_12345"
        let result = L10n.string(key)
        #expect(result == key)
    }

    // Test 3: plural variation via NSString format (Phase 1.2 補 .xcstrings plural 後才會綠)。
    @Test func test_format_plural_variation_via_NSString_format() async throws {
        let store = AppLanguageStore.shared
        store.setLanguage(.english)
        defer { store.setLanguage(.system) }

        let one = L10n.format("card_count_plural", Int64(1))
        let many = L10n.format("card_count_plural", Int64(5))

        // Phase 0 階段 .xcstrings plural variation 尚未補,此 test 應紅。
        // Phase 1.2 補完後應綠:"1 card" / "5 cards"。
        #expect(one == "1 card", "expected English singular, got: \(one)")
        #expect(many == "5 cards", "expected English plural, got: \(many)")
    }
}
