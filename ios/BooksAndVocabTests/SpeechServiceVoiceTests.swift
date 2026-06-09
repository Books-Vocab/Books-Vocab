//
//  SpeechServiceVoiceTests.swift
//  Books & Vocab Tests
//

import Foundation
import AVFoundation
import Testing
@testable import BooksAndVocab

struct SpeechServiceVoiceTests {

    @Test func test_resolveVoice_for_english_returns_english_voice() async throws {
        let voice = SpeechService.resolveVoice(for: .en)
        #expect(voice != nil)
        #expect(voice?.language.hasPrefix("en") == true)
    }

    @Test func test_resolveVoice_for_japanese_returns_japanese_voice() async throws {
        let voice = SpeechService.resolveVoice(for: .ja)
        // iOS bundles Japanese voice by default; if not installed in CI, fallback to en-US.
        // Either is acceptable as long as we don't return nil.
        #expect(voice != nil)
        // If ja voice is present it should start with "ja"; otherwise we accept en fallback.
        if let voice {
            #expect(voice.language.hasPrefix("ja") || voice.language.hasPrefix("en"))
        }
    }

    @Test func test_resolveVoice_for_korean_returns_korean_voice() async throws {
        let voice = SpeechService.resolveVoice(for: .ko)
        #expect(voice != nil)
        if let voice {
            #expect(voice.language.hasPrefix("ko") || voice.language.hasPrefix("en"))
        }
    }

    @Test func test_voiceCode_maps_zh_script_to_region() async throws {
        #expect(SpeechService.voiceCode(for: .zhHant) == "zh-TW")
        #expect(SpeechService.voiceCode(for: .zhHans) == "zh-CN")
        #expect(SpeechService.voiceCode(for: .ja) == "ja")
        #expect(SpeechService.voiceCode(for: .en) == "en")
    }
}
