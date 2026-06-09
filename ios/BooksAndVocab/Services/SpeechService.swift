//
//  SpeechService.swift
//  Books & Vocab
//
//  Created by 陳亮宇 on 2026/2/25.
//

import AVFoundation

/// 朗讀服務 — 使用 iOS 內建 TTS,零成本。
/// 語音對應 `TranslationLanguage.currentSource`,因此查日文單字會用日文語音念。
final class SpeechService: Speaking {
    static let shared = SpeechService()

    private let synthesizer = AVSpeechSynthesizer()

    /// 解析 source language → BCP-47 voice code,缺對應語音時 fallback en-US。
    /// Internal for tests.
    static func resolveVoice(for source: TranslationLanguage = TranslationLanguage.currentSource)
        -> AVSpeechSynthesisVoice?
    {
        // AVSpeechSynthesisVoice's catalog keys voices by **region-tagged** BCP-47
        // (e.g. "zh-TW" / "zh-CN"), not script-tagged ("zh-Hant" / "zh-Hans").
        // For non-Chinese languages a bare lang code resolves automatically.
        let code = voiceCode(for: source)
        return AVSpeechSynthesisVoice(language: code)
            ?? AVSpeechSynthesisVoice(language: "en-US")
    }

    /// Internal: maps a `TranslationLanguage` to the BCP-47 region tag that
    /// `AVSpeechSynthesisVoice` actually recognises.
    static func voiceCode(for source: TranslationLanguage) -> String {
        switch source {
        case .zhHant: return "zh-TW"
        case .zhHans: return "zh-CN"
        case .en, .ja, .ko, .fr, .de, .es:
            return source.rawValue
        }
    }

    func speak(_ text: String) {
        synthesizer.stopSpeaking(at: .immediate)

        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = Self.resolveVoice()
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.85
        utterance.pitchMultiplier = 1.0

        synthesizer.speak(utterance)
    }
}
