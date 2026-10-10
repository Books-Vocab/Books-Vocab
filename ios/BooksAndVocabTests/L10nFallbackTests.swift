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

    // Tier 2: 當前 locale 缺鍵時回 en 值,而非 key 原文。
    // 合成 fixture bundle(臨時 .lproj),key 只存在於 en;不選真實 key,
    // 因為真實 key 會被翻譯進 ja(例如 "初始間隔" 已於 f2c943461 補入 ja),前提即失效。
    @Test func test_key_missing_in_current_locale_falls_back_to_en_value() throws {
        let root = makeFixtureRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let key = "__l10n_fixture_fallback_key__"
        let ja = try fixtureBundle(root: root, language: "ja", strings: [:])
        let en = try fixtureBundle(root: root, language: "en", strings: [key: "Fixture English"])

        let result = L10n.lookup(key, in: ja, fallback: en)

        #expect(result == "Fixture English", "expected en fallback, got: \(result)")
    }

    // Tier 1 優先: 當前 locale 有鍵時,必須回當前 locale 的值,即使 en 有不同的值。
    @Test func test_current_locale_value_wins_over_en() throws {
        let root = makeFixtureRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let key = "__l10n_fixture_priority_key__"
        let ja = try fixtureBundle(root: root, language: "ja", strings: [key: "Fixture Japanese"])
        let en = try fixtureBundle(root: root, language: "en", strings: [key: "Fixture English"])

        let result = L10n.lookup(key, in: ja, fallback: en)

        #expect(result == "Fixture Japanese", "tier-1 value must win over en, got: \(result)")
    }

    // 所有 locale 都缺鍵時回 key 本身。CJK 合成 key 同時驗證:不會被翻譯或漏成其他字面。
    @Test func test_cjk_key_missing_everywhere_returns_key_itself() throws {
        let root = makeFixtureRoot()
        defer { try? FileManager.default.removeItem(at: root) }
        let key = "未登錄的合成鍵值測試"
        let ja = try fixtureBundle(root: root, language: "ja", strings: [:])
        let en = try fixtureBundle(root: root, language: "en", strings: [:])

        #expect(L10n.lookup(key, in: ja, fallback: en) == key)
        #expect(L10n.string(key, language: .japanese) == key)
    }

    // Test 2: 所有 locale 都缺鍵時,回 key 本身(真實 bundle 路徑)。
    @Test func test_missing_in_all_locales_returns_key_itself() async throws {
        let key = "__definitely_missing_key_xyz_12345"
        let result = L10n.string(key)
        #expect(result == key)
    }

    // card_count_plural 定義於 Localizable.stringsdict(5 個 locale 皆有),
    // 以 NSString format 觸發 plural variation;en 為穩定 reference,此 test 應為綠。
    @Test func test_format_plural_variation_via_NSString_format() async throws {
        let store = AppLanguageStore.shared
        store.setLanguage(.english)
        defer { store.setLanguage(.system) }

        let one = L10n.format("card_count_plural", Int64(1))
        let many = L10n.format("card_count_plural", Int64(5))

        #expect(one == "1 card", "expected English singular, got: \(one)")
        #expect(many == "5 cards", "expected English plural, got: \(many)")
    }

    private func makeFixtureRoot() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("l10n-fallback-\(UUID().uuidString)", isDirectory: true)
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
}
