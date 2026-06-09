//
//  SpeechServiceTests.swift
//  Books & Vocab Tests
//
//  Pins SpeechService.voiceCode(for:) — the mapping from TranslationLanguage to
//  BCP-47 region tags that AVSpeechSynthesisVoice recognises. Chinese variants
//  are the only special case; all others pass through rawValue.
//

import Foundation
import Testing
@testable import BooksAndVocab

struct SpeechServiceTests {

    // MARK: - voiceCode

    @Test func zhHantMapsToZhTW() {
        #expect(SpeechService.voiceCode(for: .zhHant) == "zh-TW")
    }

    @Test func zhHansMapsToZhCN() {
        #expect(SpeechService.voiceCode(for: .zhHans) == "zh-CN")
    }

    @Test func englishPassesThroughRawValue() {
        #expect(SpeechService.voiceCode(for: .en) == "en")
    }

    @Test func japanesePassesThroughRawValue() {
        #expect(SpeechService.voiceCode(for: .ja) == "ja")
    }

    @Test func koreanPassesThroughRawValue() {
        #expect(SpeechService.voiceCode(for: .ko) == "ko")
    }

    @Test func frenchPassesThroughRawValue() {
        #expect(SpeechService.voiceCode(for: .fr) == "fr")
    }

    @Test func germanPassesThroughRawValue() {
        #expect(SpeechService.voiceCode(for: .de) == "de")
    }

    @Test func spanishPassesThroughRawValue() {
        #expect(SpeechService.voiceCode(for: .es) == "es")
    }

    // MARK: - resolveVoice

    @Test func resolveVoiceReturnsNonNilForAllSupportedLanguages() {
        for language in TranslationLanguage.sourceLanguages {
            let voice = SpeechService.resolveVoice(for: language)
            #expect(voice != nil, "expected a voice for \(language)")
        }
    }

    @Test func resolveVoiceFallsBackToEnUSForUnknown() {
        // Even if an unsupported language is passed, resolveVoice falls back
        // to en-US rather than returning nil.
        let voice = SpeechService.resolveVoice(for: .en)
        #expect(voice != nil)
    }
}
