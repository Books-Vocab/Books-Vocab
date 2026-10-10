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
    // 使用合成 fixture bundle(臨時 .lproj),key 只存在於 en。不選真實 key:
    // 真實 key 會被翻譯進 ja(例如 "初始間隔" 已於 f2c943461 補入 ja),前提即失效。
    @Test func test_missing_key_falls_back_to_english_not_chinese_key() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("l10n-fallback-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let key = "__l10n_fixture_fallback_key__"
        let ja = try fixtureBundle(root: root, language: "ja", strings: [:])
        let en = try fixtureBundle(root: root, language: "en", strings: [key: "Fixture English"])

        let result = L10n.lookup(key, in: ja, fallback: en)

        #expect(result == "Fixture English", "expected en fallback, got: \(result)")
    }

    /// Builds a minimal `<language>.lproj/Localizable.strings` bundle on disk,
    /// the same layout `Bundle.main` ships, so `localizedString` exercises real Foundation lookup.
    private func fixtureBundle(root: URL, language: String, strings: [String: String]) throws -> Bundle {
        let dir = root.appendingPathComponent("\(language).lproj", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        var body = "/* fixture */\n"
        for (k, v) in strings { body += "\"\(k)\" = \"\(v)\";\n" }
        try body.write(to: dir.appendingPathComponent("Localizable.strings"), atomically: true, encoding: .utf8)
        return try #require(Bundle(path: dir.path))
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
