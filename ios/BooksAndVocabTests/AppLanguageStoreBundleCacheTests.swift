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

struct AppLanguageStoreBundleCacheTests {

    @Test func stringBundleDoesNotReresolveForStableLanguage() {
        let store = AppLanguageStore.shared
        store.setLanguage(.english)
        defer { store.setLanguage(.system) }

        _ = store.stringBundle // prime（首讀允許解析一次）
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
