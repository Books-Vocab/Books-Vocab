//
//  ServerURLOverrideTests.swift
//  BooksAndVocabTests
//
//  KG_UI_TEST_SERVER_URL 是 UI test 的網路封閉 seam：fixture 注入假 session 後
//  絕不可打到真 backend（真 401 → 登出 + clearLocalData 摧毀 fixture 世界；
//  真 catalog sync → reconcile tombstone 掉 seeded series）。
//  這裡測的是純函式解析層；PodcastSyncService.baseURL 等消費點由 Auth flow
//  UI test 守門。
//

import Testing
@testable import BooksAndVocab

struct ServerURLOverrideTests {
    @Test func appliesNormalizedOverrideWhenUITesting() {
        #expect(
            KGService.uiTestServerURLOverride(
                arguments: ["-ui-testing"],
                environment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9/"]
            ) == "http://127.0.0.1:9"
        )
    }

    @Test func ignoredOutsideUITesting() {
        #expect(
            KGService.uiTestServerURLOverride(
                arguments: [],
                environment: ["KG_UI_TEST_SERVER_URL": "http://127.0.0.1:9"]
            ) == nil
        )
    }

    @Test func missingOrEmptyOverrideIsNil() {
        #expect(
            KGService.uiTestServerURLOverride(
                arguments: ["-ui-testing"],
                environment: [:]
            ) == nil
        )
        #expect(
            KGService.uiTestServerURLOverride(
                arguments: ["-ui-testing"],
                environment: ["KG_UI_TEST_SERVER_URL": ""]
            ) == nil
        )
    }

    /// Whitespace-only 不可掉進 normalizeServerURL 的空字串 fallback
    ///（= 本機 dev server），否則垃圾 override 會靜默打洞 hermetic 世界。
    @Test func whitespaceOnlyOverrideIsNil() {
        #expect(
            KGService.uiTestServerURLOverride(
                arguments: ["-ui-testing"],
                environment: ["KG_UI_TEST_SERVER_URL": "  \n"]
            ) == nil
        )
    }
}
