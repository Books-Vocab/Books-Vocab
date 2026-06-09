//
//  TranslationLanguageDefaultTests.swift
//  Books & Vocab Tests
//

import Foundation
import Testing
@testable import BooksBrowser

struct TranslationLanguageDefaultTests {

    @Test func test_inferSource_zhHans_returns_zhHans() async throws {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: TranslationLanguage.targetLanguages,
            preferred: ["zh-Hans-CN", "en"]
        )
        #expect(result == .zhHans, "got \(String(describing: result))")
    }

    @Test func test_inferTarget_zhHant_returns_zhHant() async throws {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: TranslationLanguage.targetLanguages,
            preferred: ["zh-Hant-TW", "en"]
        )
        #expect(result == .zhHant)
    }

    @Test func test_inferSource_bare_zh_falls_back_to_zhHant() async throws {
        // 沒有 script tag 預設給繁體(較常見的傳統設定)
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: TranslationLanguage.targetLanguages,
            preferred: ["zh", "en"]
        )
        #expect(result == .zhHant)
    }

    @Test func test_inferSource_enGB_picks_en() async throws {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: TranslationLanguage.sourceLanguages,
            preferred: ["en-GB"]
        )
        #expect(result == .en)
    }

    @Test func test_inferSource_deAT_picks_de() async throws {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: TranslationLanguage.sourceLanguages,
            preferred: ["de-AT", "en"]
        )
        #expect(result == .de)
    }

    @Test func test_inferSource_unsupported_returns_nil() async throws {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: TranslationLanguage.sourceLanguages,
            preferred: ["pt-BR", "ru"]
        )
        #expect(result == nil)
    }

    @Test func test_inferSource_japanese_then_english_picks_ja() async throws {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: TranslationLanguage.sourceLanguages,
            preferred: ["ja-JP", "en-US"]
        )
        #expect(result == .ja)
    }

    @Test func test_setter_writes_updated_at_timestamp() async throws {
        // Snapshot to restore after test.
        let prevSource = TranslationLanguage.currentSource
        let prevSourceUpdatedAt = TranslationLanguage.sourceUpdatedAt
        defer {
            TranslationLanguage.currentSource = prevSource
            if let ts = prevSourceUpdatedAt {
                UserDefaults.standard.set(ts, forKey: "translation_source_lang_updated_at")
            }
        }

        let before = Date().timeIntervalSince1970
        TranslationLanguage.currentSource = .ja
        let after = Date().timeIntervalSince1970

        let updatedAt = TranslationLanguage.sourceUpdatedAt
        #expect(updatedAt != nil)
        if let updatedAt {
            #expect(updatedAt >= before)
            #expect(updatedAt <= after + 0.1)
        }
    }

    @Test func test_applyServerColdStart_writes_local_with_server_timestamp() async throws {
        // TranslationLanguage 用 UserDefaults.standard + 單例 KVS，靠 snapshot/restore
        // 隔離（比照 test_setter_writes_updated_at_timestamp）。
        let prevSource = TranslationLanguage.currentSource
        let prevTarget = TranslationLanguage.currentTarget
        let prevS = TranslationLanguage.sourceUpdatedAt
        let prevT = TranslationLanguage.targetUpdatedAt
        defer {
            TranslationLanguage.restore(
                source: prevSource, sourceUpdatedAt: prevS,
                target: prevTarget, targetUpdatedAt: prevT
            )
        }

        TranslationLanguage.applyServerColdStart(source: .ja, target: .ko, updatedAt: 99999)

        // cold-start 套 server 值到本地層，source/target 共用 server 的單一 group 時戳。
        #expect(UserDefaults.standard.string(forKey: "translation_source_lang") == "ja")
        #expect(UserDefaults.standard.string(forKey: "translation_target_lang") == "ko")
        #expect(UserDefaults.standard.object(forKey: "translation_source_lang_updated_at") as? Double == 99999)
        #expect(UserDefaults.standard.object(forKey: "translation_target_lang_updated_at") as? Double == 99999)
    }
}
