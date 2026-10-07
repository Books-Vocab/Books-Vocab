//
//  AppAudioSession.swift
//  Books & Vocab
//
//  App-level AVAudioSession policy for short, non-long-form audio: TTS
//  pronunciation (`SpeechService`) and UI feedback tones
//  (`FeedbackAudioService`). Each use sets an explicit category before it
//  plays, so silent-switch behaviour no longer depends on whether a podcast
//  left the shared session in `.playback` earlier in the process (#2110).
//
//  Podcast playback configures its own `.playback` / `.spokenAudio` session in
//  `PodcastAudioEngine`; while a podcast player session is open this type
//  leaves the session alone so a tap tone can never demote a playing (or
//  paused, about to resume) podcast to `.ambient`.
//

import AVFoundation
import MediaPlayer

/// What the app is about to play through the shared audio session.
enum AppAudioUse: Equatable {
    /// User-initiated pronunciation: audible with the silent switch on, ducks
    /// other apps' music and pauses other spoken audio while it speaks.
    case speech
    /// Non-verbal UI feedback: honours the silent switch and mixes with other
    /// apps' audio without interrupting it.
    case uiTone
}

struct AudioSessionConfiguration: Equatable {
    let category: AVAudioSession.Category
    let mode: AVAudioSession.Mode
    let options: AVAudioSession.CategoryOptions

    static func forUse(_ use: AppAudioUse) -> AudioSessionConfiguration {
        switch use {
        case .speech:
            return AudioSessionConfiguration(
                category: .playback,
                mode: .default,
                options: [.duckOthers, .interruptSpokenAudioAndMixWithOthers]
            )
        case .uiTone:
            return AudioSessionConfiguration(category: .ambient, mode: .default, options: [])
        }
    }
}

/// Narrow seam over `AVAudioSession` so the policy is unit-testable.
protocol AudioSessionControlling: AnyObject {
    var currentConfiguration: AudioSessionConfiguration { get }
    func apply(_ configuration: AudioSessionConfiguration) throws
    func setActive(_ active: Bool, notifyOthersOnDeactivation: Bool) throws
}

final class SystemAudioSessionController: AudioSessionControlling {
    private var session: AVAudioSession { AVAudioSession.sharedInstance() }

    var currentConfiguration: AudioSessionConfiguration {
        AudioSessionConfiguration(
            category: session.category,
            mode: session.mode,
            options: session.categoryOptions
        )
    }

    func apply(_ configuration: AudioSessionConfiguration) throws {
        try session.setCategory(
            configuration.category,
            mode: configuration.mode,
            options: configuration.options
        )
    }

    func setActive(_ active: Bool, notifyOthersOnDeactivation: Bool) throws {
        try session.setActive(
            active,
            options: notifyOthersOnDeactivation ? [.notifyOthersOnDeactivation] : []
        )
    }
}

final class AppAudioSession {
    static let shared = AppAudioSession()

    private let controller: AudioSessionControlling
    private let isLongFormPlaybackActive: () -> Bool
    private let lock = NSLock()
    private var speechActive = false

    /// - Parameter isLongFormPlaybackActive: true while a podcast player
    ///   session owns the shared session. Default reads the lock-screen
    ///   now-playing info, which `PodcastAudioEngine` sets on load and clears
    ///   on `shutdown()`.
    init(
        controller: AudioSessionControlling = SystemAudioSessionController(),
        isLongFormPlaybackActive: @escaping () -> Bool = {
            MPNowPlayingInfoCenter.default().nowPlayingInfo != nil
        }
    ) {
        self.controller = controller
        self.isLongFormPlaybackActive = isLongFormPlaybackActive
    }

    /// Configure the shared session for `use`. Returns whether this call
    /// changed or activated the session (false = deferred to the current
    /// owner, or the configuration was already in place).
    @discardableResult
    func prepare(for use: AppAudioUse) -> Bool {
        guard !isLongFormPlaybackActive() else { return false }
        lock.lock()
        defer { lock.unlock() }
        // A tone fired mid-utterance must not demote speech to `.ambient`.
        if use == .uiTone, speechActive { return false }

        let target = AudioSessionConfiguration.forUse(use)
        do {
            var changed = false
            if controller.currentConfiguration != target {
                try controller.apply(target)
                changed = true
            }
            if use == .speech {
                // Explicit activation so `endSpeech()` pairs with it and
                // un-ducks other apps.
                try controller.setActive(true, notifyOthersOnDeactivation: false)
                speechActive = true
                changed = true
            }
            return changed
        } catch {
            AppLog.app.warning("[AudioSession] prepare(\(String(describing: use))) failed: \(error.localizedDescription)")
            return false
        }
    }

    /// Speech finished or was cancelled: release the session so ducked apps
    /// return to full volume. Skipped while a podcast owns the session.
    func endSpeech() {
        lock.lock()
        defer { lock.unlock() }
        guard speechActive else { return }
        speechActive = false
        guard !isLongFormPlaybackActive() else { return }
        do {
            try controller.setActive(false, notifyOthersOnDeactivation: true)
        } catch {
            AppLog.app.warning("[AudioSession] endSpeech deactivate failed: \(error.localizedDescription)")
        }
    }
}
