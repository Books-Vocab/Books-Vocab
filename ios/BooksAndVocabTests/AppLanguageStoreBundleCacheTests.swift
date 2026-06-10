//
//  AppLanguageStoreBundleCacheTests.swift
//  Books & Vocab Tests
//
//  Pins the stringBundle resolution-cache contract. Device time-profile
//  (2026-06-10 settle-stall war) showed L10n.lookup paying
//  `Bundle.main.path(forResource:)` + `Bundle(path:)` on EVERY localized
//  string read — dozens of times per review-card settle. The cache must
//  (a) eliminate repeat resolution for a stable language and
//  (b) never stick to a stale language after setLanguage.
//

import Foundation
import Testing
@testable import BooksAndVocab

// .serialized: tests mutate AppLanguageStore.shared singleton.
@Suite(.serialized) @MainActor
struct AppLanguageStoreBundleCacheTests {

    @Test func stringBundleDoesNotReresolveForStableLanguage() {
        let store = AppLanguageStore.shared
        // 暖滿全部語言：cache 永久保留，先把每語言的首次解析都吃掉，
        // 封死「並行 suite 的 setLanguage 首碰某語言 → count +1」的跨
        // suite 視窗（.serialized 只序列化本 suite 內）。
        for language in AppLanguage.allCases {
            store.setLanguage(language)
            _ = store.stringBundle
        }
        store.setLanguage(.english)
        defer { store.setLanguage(.system) }

        _ = store.stringBundle // prime（已暖，不應再解析）
        let primed = store.bundleResolutionCount
        _ = store.stringBundle
        _ = store.stringBundle
        _ = store.stringBundle
        #expect(store.bundleResolutionCount == primed)
    }

    @Test func stringBundleReflectsLanguageChange() {
        let store = AppLanguageStore.shared
        store.setLanguage(.english)
        defer { store.setLanguage(.system) }

        let en = store.stringBundle
        #expect(en.bundlePath.hasSuffix("en.lproj"))

        store.setLanguage(.japanese)
        let ja = store.stringBundle
        #expect(ja.bundlePath.hasSuffix("ja.lproj"))
        #expect(en !== ja)
    }
}
