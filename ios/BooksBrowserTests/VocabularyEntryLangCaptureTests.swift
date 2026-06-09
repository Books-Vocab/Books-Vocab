//
//  VocabularyEntryLangCaptureTests.swift
//  Books & Vocab Tests
//

import Foundation
import Testing
@testable import BooksBrowser

@Suite(.serialized)
struct VocabularyEntryLangCaptureTests {

    @Test func test_init_captures_current_source_and_target() async throws {
        // Snapshot to restore.
        let prevSource = TranslationLanguage.currentSource
        let prevTarget = TranslationLanguage.currentTarget
        let prevSourceTs = TranslationLanguage.sourceUpdatedAt
        let prevTargetTs = TranslationLanguage.targetUpdatedAt
        defer {
            TranslationLanguage.restore(
                source: prevSource,
                sourceUpdatedAt: prevSourceTs,
                target: prevTarget,
                targetUpdatedAt: prevTargetTs
            )
        }

        TranslationLanguage.currentSource = .ja
        TranslationLanguage.currentTarget = .zhHant

        let entry = VocabularyEntry(
            word: "辞書",
            translation: "字典",
            context: "辞書を引く",
            bookTitle: "Test Book"
        )

        #expect(entry.sourceLang == "ja")
        #expect(entry.targetLang == "zh-Hant")
    }

    @Test func test_init_explicit_override_wins() async throws {
        let entry = VocabularyEntry(
            word: "Hello",
            translation: "你好",
            context: "Hello world",
            bookTitle: "Test Book",
            sourceLang: "en",
            targetLang: "zh-Hans"
        )
        #expect(entry.sourceLang == "en")
        #expect(entry.targetLang == "zh-Hans")
    }
}
