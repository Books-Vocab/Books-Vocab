//
//  AppTipsLocalizationTests.swift
//  Books & Vocab Tests
//
//  Tip 結構不易直接 unit-test render 出來的字串(Text 內部沒公開 API),
//  但 Phase 2 把所有 Tip property 改成走 L10n.string,因此驗證 L10n
//  key→value 鏈在 5 語言下解析正確即等同驗 Tip 字串會更新。
//

import Foundation
import Testing
@testable import BooksAndVocab

// .serialized: tests mutate AppLanguageStore.shared singleton; parallel
// execution would race on `selection`/UserDefaults.
@Suite(.serialized)
@MainActor
struct AppTipsLocalizationTests {

    @Test func test_tip_keys_resolve_in_english() async throws {
        let store = AppLanguageStore.shared
        store.setLanguage(.english)
        defer { store.setLanguage(.system) }

        for key in [
            "tip_long_press_title", "tip_long_press_message",
            "tip_sync_vocab_title", "tip_sync_vocab_message",
            "tip_epub_guide_title", "tip_epub_guide_message"
        ] {
            let v = L10n.string(key)
            #expect(v != key, "missing en translation for \(key)")
            let hasChinese = v.unicodeScalars.contains { (0x4E00...0x9FFF).contains($0.value) }
            #expect(hasChinese == false, "english tip leak: \(key) = \(v)")
        }
    }

    @Test func test_tip_keys_switch_language_changes_value() async throws {
        let store = AppLanguageStore.shared
        store.setLanguage(.english)
        let en = L10n.string("tip_long_press_title")
        store.setLanguage(.japanese)
        let ja = L10n.string("tip_long_press_title")
        defer { store.setLanguage(.system) }

        #expect(en != ja, "tip didn't change between en (\(en)) and ja (\(ja))")
    }
}
