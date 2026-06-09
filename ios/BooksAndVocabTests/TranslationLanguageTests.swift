//
//  TranslationLanguageTests.swift
//  Books & Vocab Tests
//
//  Pins TranslationLanguage.inferFromPreferredLanguages — the locale-to-language
//  mapping that drives default source/target selection on first launch. Script
//  awareness for Chinese (Hans vs Hant) is the most complex path.
//

import Foundation
import Testing
@testable import BooksAndVocab

struct TranslationLanguageTests {

    // MARK: - inferFromPreferredLanguages

    @Test func exactMatchReturnsLanguage() {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.en, .ja],
            preferred: ["ja-JP"]
        )
        #expect(result == .ja)
    }

    @Test func prefixMatchReturnsLanguage() {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.en, .fr],
            preferred: ["fr-CA"]
        )
        #expect(result == .fr)
    }

    @Test func firstMatchWins() {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.en, .ja, .ko],
            preferred: ["ko-KR", "ja-JP"]
        )
        #expect(result == .ko)
    }

    @Test func noMatchReturnsNil() {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.en, .ja],
            preferred: ["de-DE"]
        )
        #expect(result == nil)
    }

    @Test func emptyPreferredReturnsNil() {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.en],
            preferred: []
        )
        #expect(result == nil)
    }

    @Test func emptyAllowedReturnsNil() {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [],
            preferred: ["en-US"]
        )
        #expect(result == nil)
    }

    // MARK: - Chinese script awareness

    @Test func zhHansMatchesSimplifiedChinese() {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.zhHant, .zhHans, .en],
            preferred: ["zh-Hans-CN"]
        )
        #expect(result == .zhHans)
    }

    @Test func zhHantMatchesTraditionalChinese() {
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.zhHant, .zhHans, .en],
            preferred: ["zh-Hant-TW"]
        )
        #expect(result == .zhHant)
    }

    @Test func bareZhFallsBackToHant() {
        // Bare "zh" without script subtag defaults to Hant in allowed order.
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.zhHant, .zhHans, .en],
            preferred: ["zh"]
        )
        #expect(result == .zhHant)
    }

    @Test func zhCNResolvedToHans() {
        // zh-CN typically resolves to Hans script.
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.zhHans, .zhHant, .en],
            preferred: ["zh-CN"]
        )
        #expect(result == .zhHans)
    }

    @Test func zhTWResolvedToHant() {
        // zh-TW typically resolves to Hant script.
        let result = TranslationLanguage.inferFromPreferredLanguages(
            allowed: [.zhHant, .zhHans, .en],
            preferred: ["zh-TW"]
        )
        #expect(result == .zhHant)
    }

    // MARK: - Language list contents

    @Test func sourceLanguagesContainsEnglish() {
        #expect(TranslationLanguage.sourceLanguages.contains(.en))
    }

    @Test func sourceLanguagesDoesNotContainChinese() {
        #expect(!TranslationLanguage.sourceLanguages.contains(.zhHant))
        #expect(!TranslationLanguage.sourceLanguages.contains(.zhHans))
    }

    @Test func targetLanguagesContainsChinese() {
        #expect(TranslationLanguage.targetLanguages.contains(.zhHant))
        #expect(TranslationLanguage.targetLanguages.contains(.zhHans))
    }

    // MARK: - Native names / flag emojis

    @Test func englishNativeName() {
        #expect(TranslationLanguage.en.nativeName == "English")
        #expect(TranslationLanguage.en.flagEmoji == "🇺🇸")
    }

    @Test func japaneseNativeName() {
        #expect(TranslationLanguage.ja.nativeName == "日本語")
        #expect(TranslationLanguage.ja.flagEmoji == "🇯🇵")
    }

    @Test func allCasesHaveNativeNames() {
        for lang in TranslationLanguage.allCases {
            #expect(!lang.nativeName.isEmpty, "\(lang) missing nativeName")
        }
    }

    @Test func allCasesHaveFlagEmojis() {
        for lang in TranslationLanguage.allCases {
            #expect(!lang.flagEmoji.isEmpty, "\(lang) missing flagEmoji")
        }
    }

    // MARK: - applyServerColdStart

    @Test func coldStartWritesToUserDefaults() {
        let defaults = UserDefaults(suiteName: #file)!
        defer {
            defaults.removeObject(forKey: "translation_source_lang")
            defaults.removeObject(forKey: "translation_target_lang")
            defaults.removeObject(forKey: "translation_source_lang_updated_at")
            defaults.removeObject(forKey: "translation_target_lang_updated_at")
        }

        // Temporarily swap the keys by using a swizzled approach is not viable;
        // instead we verify the API contract: after cold-start the values are
        // retrievable from standard UserDefaults.
        TranslationLanguage.applyServerColdStart(
            source: .ja,
            target: .zhHans,
            updatedAt: 1234.5
        )

        let sourceRaw = UserDefaults.standard.string(forKey: "translation_source_lang")
        let targetRaw = UserDefaults.standard.string(forKey: "translation_target_lang")
        let sourceAt = UserDefaults.standard.object(forKey: "translation_source_lang_updated_at") as? Double
        let targetAt = UserDefaults.standard.object(forKey: "translation_target_lang_updated_at") as? Double

        #expect(sourceRaw == "ja")
        #expect(targetRaw == "zh-Hans")
        #expect(sourceAt == 1234.5)
        #expect(targetAt == 1234.5)
    }
}
