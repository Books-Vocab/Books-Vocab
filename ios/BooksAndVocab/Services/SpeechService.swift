//
//  SpeechService.swift
//  Books & Vocab
//
//  Created by 陳亮宇 on 2026/2/25.
//

import AVFoundation

/// 朗讀服務 — 使用 iOS 內建 TTS,零成本。
/// 語音對應 `TranslationLanguage.currentSource`,因此查日文單字會用日文語音念。
/// 發音前經 `AppAudioSession` 設定明確的 `.playback` category（靜音開關下仍出聲、
/// duck 其他 app），講完／被取消後釋放 session 讓其他 app 恢復音量（#2110）。
final class SpeechService: NSObject, Speaking {
    static let shared = SpeechService()

    private let synthesizer = AVSpeechSynthesizer()
    private let audioSession: AppAudioSession
    /// 最新一句 utterance；只有它結束才釋放 session（`stopSpeaking` 取消的舊句不算）。
    /// 只在 main thread 讀寫。Internal for tests.
    private(set) var currentUtterance: AVSpeechUtterance?

    init(audioSession: AppAudioSession) {
        self.audioSession = audioSession
        super.init()
        synthesizer.delegate = self
    }

    override convenience init() {
        self.init(audioSession: .shared)
    }

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

        currentUtterance = utterance
        audioSession.prepare(for: .speech)
        synthesizer.speak(utterance)
    }

    /// Internal for tests: release the session only when the latest utterance ends.
    func utteranceDidEnd(_ utterance: AVSpeechUtterance) {
        guard utterance === currentUtterance else { return }
        currentUtterance = nil
        audioSession.endSpeech()
    }
}

extension SpeechService: AVSpeechSynthesizerDelegate {
    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        DispatchQueue.main.async { self.utteranceDidEnd(utterance) }
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        DispatchQueue.main.async { self.utteranceDidEnd(utterance) }
    }
}
