//
//  AppLanguageTests.swift
//  Books & Vocab Tests
//
//  Pins AppLanguage localizationCode and locale mappings. A regression here
//  breaks localization for entire user populations.
//

import Foundation
import Testing
@testable import BooksAndVocab

struct AppLanguageTests {

    // MARK: - localizationCode

    @Test func systemLocalizationCodeIsNil() {
        #expect(AppLanguage.system.localizationCode == nil)
    }

    @Test func englishLocalizationCode() {
        #expect(AppLanguage.english.localizationCode == "en")
    }

    @Test func traditionalChineseLocalizationCode() {
        #expect(AppLanguage.traditionalChinese.localizationCode == "zh-Hant")
    }

    @Test func simplifiedChineseLocalizationCode() {
        #expect(AppLanguage.simplifiedChinese.localizationCode == "zh-Hans")
    }

    @Test func japaneseLocalizationCode() {
        #expect(AppLanguage.japanese.localizationCode == "ja")
    }

    @Test func koreanLocalizationCode() {
        #expect(AppLanguage.korean.localizationCode == "ko")
    }

    // MARK: - locale

    @Test func englishLocaleIdentifier() {
        #expect(AppLanguage.english.locale.identifier == "en")
    }

    @Test func traditionalChineseLocaleIdentifier() {
        #expect(AppLanguage.traditionalChinese.locale.identifier == "zh-Hant")
    }

    @Test func simplifiedChineseLocaleIdentifier() {
        #expect(AppLanguage.simplifiedChinese.locale.identifier == "zh-Hans")
    }

    @Test func japaneseLocaleIdentifier() {
        #expect(AppLanguage.japanese.locale.identifier == "ja")
    }

    @Test func koreanLocaleIdentifier() {
        #expect(AppLanguage.korean.locale.identifier == "ko")
    }

    // MARK: - CaseIterable

    @Test func allCasesContainsAllLanguages() {
        let all = AppLanguage.allCases
        #expect(all.contains(.system))
        #expect(all.contains(.english))
        #expect(all.contains(.traditionalChinese))
        #expect(all.contains(.simplifiedChinese))
        #expect(all.contains(.japanese))
        #expect(all.contains(.korean))
    }

    @Test func idMatchesRawValue() {
        for lang in AppLanguage.allCases {
            #expect(lang.id == lang.rawValue)
        }
    }
}
