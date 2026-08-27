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

@Suite(.serialized)
struct TranslationLanguageTests {

    init() {
        // The app composition root suspends the preference namespace when the
        // host starts without an authenticated session. These tests exercise
        // the legacy guest-compatible API directly, so explicitly enter that
        // namespace before each suite instance.
        TranslationLanguage.activateAccount(nil)
    }

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

    // MARK: - Server LWW

    @Test func serverTranslationAppliesWhenServerTimestampIsNewer() {
        let previousSource = TranslationLanguage.currentSource
        let previousTarget = TranslationLanguage.currentTarget
        let previousSourceUpdatedAt = TranslationLanguage.sourceUpdatedAt
        let previousTargetUpdatedAt = TranslationLanguage.targetUpdatedAt
        defer {
            TranslationLanguage.restore(
                source: previousSource,
                sourceUpdatedAt: previousSourceUpdatedAt,
                target: previousTarget,
                targetUpdatedAt: previousTargetUpdatedAt
            )
        }

        TranslationLanguage.restore(
            source: .en,
            sourceUpdatedAt: 100,
            target: .zhHant,
            targetUpdatedAt: 100
        )

        let applied = TranslationLanguage.applyServer(
            source: .ja,
            target: .zhHans,
            serverUpdatedAt: 200
        )

        #expect(applied)
        #expect(TranslationLanguage.currentSource == .ja)
        #expect(TranslationLanguage.currentTarget == .zhHans)
        #expect(TranslationLanguage.sourceUpdatedAt == 200)
        #expect(TranslationLanguage.targetUpdatedAt == 200)
    }

    @Test func serverTranslationIgnoredWhenLocalTimestampIsNewer() {
        let previousSource = TranslationLanguage.currentSource
        let previousTarget = TranslationLanguage.currentTarget
        let previousSourceUpdatedAt = TranslationLanguage.sourceUpdatedAt
        let previousTargetUpdatedAt = TranslationLanguage.targetUpdatedAt
        defer {
            TranslationLanguage.restore(
                source: previousSource,
                sourceUpdatedAt: previousSourceUpdatedAt,
                target: previousTarget,
                targetUpdatedAt: previousTargetUpdatedAt
            )
        }

        TranslationLanguage.restore(
            source: .en,
            sourceUpdatedAt: 300,
            target: .zhHant,
            targetUpdatedAt: 300
        )

        let applied = TranslationLanguage.applyServer(
            source: .ja,
            target: .zhHans,
            serverUpdatedAt: 200
        )

        #expect(!applied)
        #expect(TranslationLanguage.currentSource == .en)
        #expect(TranslationLanguage.currentTarget == .zhHant)
        #expect(TranslationLanguage.sourceUpdatedAt == 300)
        #expect(TranslationLanguage.targetUpdatedAt == 300)
    }

    @Test func serverTranslationUsesServerValueWhenLocalTimestampIsAbsent() {
        let previousSource = TranslationLanguage.currentSource
        let previousTarget = TranslationLanguage.currentTarget
        let previousSourceUpdatedAt = TranslationLanguage.sourceUpdatedAt
        let previousTargetUpdatedAt = TranslationLanguage.targetUpdatedAt
        defer {
            TranslationLanguage.restore(
                source: previousSource,
                sourceUpdatedAt: previousSourceUpdatedAt,
                target: previousTarget,
                targetUpdatedAt: previousTargetUpdatedAt
            )
        }

        TranslationLanguage.restore(
            source: .en,
            sourceUpdatedAt: nil,
            target: .zhHant,
            targetUpdatedAt: nil
        )

        let applied = TranslationLanguage.applyServer(
            source: .de,
            target: .en,
            serverUpdatedAt: 400
        )

        #expect(applied)
        #expect(TranslationLanguage.currentSource == .de)
        #expect(TranslationLanguage.currentTarget == .en)
        #expect(TranslationLanguage.sourceUpdatedAt == 400)
        #expect(TranslationLanguage.targetUpdatedAt == 400)
    }

    // MARK: - Server persistence

    @Test func serverTranslationWritesToUserDefaults() {
        let previousSource = TranslationLanguage.currentSource
        let previousTarget = TranslationLanguage.currentTarget
        let previousSourceUpdatedAt = TranslationLanguage.sourceUpdatedAt
        let previousTargetUpdatedAt = TranslationLanguage.targetUpdatedAt
        defer {
            TranslationLanguage.restore(
                source: previousSource,
                sourceUpdatedAt: previousSourceUpdatedAt,
                target: previousTarget,
                targetUpdatedAt: previousTargetUpdatedAt
            )
        }

        let serverUpdatedAt = ([previousSourceUpdatedAt, previousTargetUpdatedAt].compactMap { $0 }.max() ?? Date().timeIntervalSince1970) + 1
        let applied = TranslationLanguage.applyServer(
            source: .ja,
            target: .zhHans,
            serverUpdatedAt: serverUpdatedAt
        )

        let sourceRaw = UserDefaults.standard.string(forKey: "translation_source_lang")
        let targetRaw = UserDefaults.standard.string(forKey: "translation_target_lang")
        let sourceAt = UserDefaults.standard.object(forKey: "translation_source_lang_updated_at") as? Double
        let targetAt = UserDefaults.standard.object(forKey: "translation_target_lang_updated_at") as? Double

        #expect(applied)
        #expect(sourceRaw == "ja")
        #expect(targetRaw == "zh-Hans")
        #expect(sourceAt == serverUpdatedAt)
        #expect(targetAt == serverUpdatedAt)
    }

    @Test @MainActor func accountScopedTranslationPairDoesNotCrossReadOrWrite() {
        let suite = "test.translation-account-scope.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        let cloud = FakeCloudKVStore()
        defer { TranslationLanguage.activateAccount(nil) }

        TranslationLanguage.activateAccount("account-a", defaults: defaults, cloud: cloud)
        TranslationLanguage.currentSource = .ja
        TranslationLanguage.currentTarget = .zhHans

        TranslationLanguage.activateAccount("account-b", defaults: defaults, cloud: cloud)
        let accountBSource = TranslationLanguage.currentSource
        let accountBTarget = TranslationLanguage.currentTarget
        #expect(accountBSource != .ja || accountBTarget != .zhHans)

        TranslationLanguage.currentSource = .de
        TranslationLanguage.currentTarget = .en
        TranslationLanguage.activateAccount("account-a", defaults: defaults, cloud: cloud)
        #expect(TranslationLanguage.currentSource == .ja)
        #expect(TranslationLanguage.currentTarget == .zhHans)

        TranslationLanguage.activateAccount("account-b", defaults: defaults, cloud: cloud)
        #expect(TranslationLanguage.currentSource == .de)
        #expect(TranslationLanguage.currentTarget == .en)
    }

    @Test @MainActor func firstAccountActivationMigratesLegacyTranslationPairOnlyOnce() {
        let suite = "test.translation-legacy-migration.\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suite)!
        let cloud = FakeCloudKVStore()
        defer {
            defaults.removePersistentDomain(forName: suite)
            TranslationLanguage.activateAccount(nil)
        }

        defaults.set("ja", forKey: "translation_source_lang")
        defaults.set(100.0, forKey: "translation_source_lang_updated_at")
        defaults.set("zh-Hans", forKey: "translation_target_lang")
        defaults.set(100.0, forKey: "translation_target_lang_updated_at")
        cloud.set("ja", forKey: "translation_source_lang")
        cloud.set(100.0, forKey: "translation_source_lang_updated_at")
        cloud.set("zh-Hans", forKey: "translation_target_lang")
        cloud.set(100.0, forKey: "translation_target_lang_updated_at")

        TranslationLanguage.activateAccount("account-a", defaults: defaults, cloud: cloud)
        #expect(TranslationLanguage.currentSource == .ja)
        #expect(TranslationLanguage.currentTarget == .zhHans)
        #expect(
            defaults.string(
                forKey: AccountPreferenceNamespace.key("translation_source_lang", accountID: "account-a")
            ) == "ja"
        )

        TranslationLanguage.activateAccount("account-b", defaults: defaults, cloud: cloud)
        #expect(TranslationLanguage.currentSource == .en)
        #expect(TranslationLanguage.currentTarget == .zhHant)
        #expect(
            defaults.string(
                forKey: AccountPreferenceNamespace.key("translation_source_lang", accountID: "account-b")
            ) == nil
        )
    }
}
