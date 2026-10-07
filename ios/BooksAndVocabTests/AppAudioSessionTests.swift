//
//  AppAudioSessionTests.swift
//  Books & Vocab Tests
//
//  #2110: TTS and UI feedback tones set an explicit audio-session category
//  before they play, independent of whether a podcast configured the shared
//  session earlier, and never reconfigure it while a podcast owns it.
//

#if os(iOS)
import AVFoundation
import Foundation
import Testing
@testable import BooksAndVocab

/// Records every call; starts in the state a podcast `shutdown()` leaves
/// behind (`.playback` / `.spokenAudio`, deactivated).
private final class FakeAudioSessionController: AudioSessionControlling {
    var currentConfiguration = AudioSessionConfiguration(
        category: .playback, mode: .spokenAudio, options: []
    )
    private(set) var applied: [AudioSessionConfiguration] = []
    private(set) var activations: [(active: Bool, notifyOthers: Bool)] = []

    func apply(_ configuration: AudioSessionConfiguration) throws {
        applied.append(configuration)
        currentConfiguration = configuration
    }

    func setActive(_ active: Bool, notifyOthersOnDeactivation: Bool) throws {
        activations.append((active, notifyOthersOnDeactivation))
    }
}

@Suite(.serialized)
@MainActor
struct AppAudioSessionTests {

    private let speechConfig = AudioSessionConfiguration(
        category: .playback, mode: .default,
        options: [.duckOthers, .interruptSpokenAudioAndMixWithOthers]
    )
    private let toneConfig = AudioSessionConfiguration(category: .ambient, mode: .default, options: [])

    private func makeSession(longForm: Bool = false) -> (AppAudioSession, FakeAudioSessionController) {
        let fake = FakeAudioSessionController()
        return (AppAudioSession(controller: fake, isLongFormPlaybackActive: { longForm }), fake)
    }

    // MARK: - Policy

    @Test func speech_sets_playback_with_ducking_and_activates() {
        let (session, fake) = makeSession()
        #expect(session.prepare(for: .speech))
        #expect(fake.applied == [speechConfig])
        #expect(fake.activations.map { $0.active } == [true])
    }

    @Test func tone_after_podcast_left_playback_sets_ambient() {
        let (session, fake) = makeSession()
        #expect(session.prepare(for: .uiTone))
        #expect(fake.applied == [toneConfig], "a tone must honour the silent switch even after a podcast left .playback")
        #expect(fake.activations.isEmpty)
    }

    @Test func tone_skips_redundant_setCategory() {
        let (session, fake) = makeSession()
        session.prepare(for: .uiTone)
        #expect(!session.prepare(for: .uiTone))
        #expect(fake.applied == [toneConfig])
    }

    @Test func open_podcast_session_is_never_reconfigured() {
        let (session, fake) = makeSession(longForm: true)
        #expect(!session.prepare(for: .speech))
        #expect(!session.prepare(for: .uiTone))
        session.endSpeech()
        #expect(fake.applied.isEmpty)
        #expect(fake.activations.isEmpty)
    }

    @Test func tone_during_speech_does_not_demote_to_ambient() {
        let (session, fake) = makeSession()
        session.prepare(for: .speech)
        #expect(!session.prepare(for: .uiTone))
        #expect(fake.applied == [speechConfig])
    }

    @Test func endSpeech_deactivates_and_notifies_others_once() {
        let (session, fake) = makeSession()
        session.prepare(for: .speech)
        session.endSpeech()
        session.endSpeech()
        #expect(fake.activations.count == 2)
        #expect(fake.activations.last?.active == false)
        #expect(fake.activations.last?.notifyOthers == true)
        #expect(session.prepare(for: .uiTone), "after speech ends, tones go back to .ambient")
        #expect(fake.applied.last == toneConfig)
    }

    // MARK: - Call sites

    @Test func speak_configures_speech_category_before_speaking() {
        let (session, fake) = makeSession()
        let speech = SpeechService(audioSession: session)
        speech.speak("word")
        #expect(fake.applied == [speechConfig])
        #expect(fake.activations.map { $0.active } == [true])
    }

    @Test func only_latest_utterance_end_releases_session() throws {
        let (session, fake) = makeSession()
        let speech = SpeechService(audioSession: session)
        speech.speak("first")
        let first = try #require(speech.currentUtterance)
        speech.speak("second")
        let second = try #require(speech.currentUtterance)

        speech.utteranceDidEnd(first)   // cancelled by the second speak()
        #expect(!fake.activations.contains { !$0.active }, "a cancelled earlier utterance must not release the session")

        speech.utteranceDidEnd(second)
        #expect(fake.activations.last?.active == false)
        #expect(speech.currentUtterance == nil)
    }

    @Test func feedback_tone_configures_ambient_category() {
        let (session, fake) = makeSession()
        let feedback = FeedbackAudioService(audioSession: session)
        feedback.play(.tap)
        #expect(fake.applied == [toneConfig])
    }
}
#endif
