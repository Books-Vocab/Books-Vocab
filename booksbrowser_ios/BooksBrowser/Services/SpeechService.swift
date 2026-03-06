//
//  SpeechService.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/25.
//

import AVFoundation

/// 英文發音服務 — 使用 iOS 內建 TTS，零成本
final class SpeechService {
    static let shared = SpeechService()

    private let synthesizer = AVSpeechSynthesizer()

    func speak(_ text: String) {
        synthesizer.stopSpeaking(at: .immediate)

        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        utterance.rate = AVSpeechUtteranceDefaultSpeechRate * 0.85
        utterance.pitchMultiplier = 1.0

        synthesizer.speak(utterance)
    }
}
