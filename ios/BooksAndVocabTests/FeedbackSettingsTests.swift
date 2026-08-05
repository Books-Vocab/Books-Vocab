import Foundation
import Testing
@testable import BooksAndVocab

@Suite(.serialized)
struct FeedbackSettingsTests {
    @Test func defaultsPreserveHapticsAndKeepNewSoundsQuiet() throws {
        let defaults = try #require(UserDefaults(suiteName: "feedback-settings-defaults"))
        defaults.removePersistentDomain(forName: "feedback-settings-defaults")
        defer { defaults.removePersistentDomain(forName: "feedback-settings-defaults") }

        let store = FeedbackSettingsStore(defaults: defaults)

        #expect(store.hapticFeedbackEnabled == true)
        #expect(store.soundFeedbackEnabled == false)
    }

    @Test func settingsPersistIndependently() throws {
        let defaults = try #require(UserDefaults(suiteName: "feedback-settings-persistence"))
        defaults.removePersistentDomain(forName: "feedback-settings-persistence")
        defer { defaults.removePersistentDomain(forName: "feedback-settings-persistence") }

        let store = FeedbackSettingsStore(defaults: defaults)
        store.setSoundFeedbackEnabled(true)
        store.setHapticFeedbackEnabled(false)

        let restored = FeedbackSettingsStore(defaults: defaults)

        #expect(restored.soundFeedbackEnabled == true)
        #expect(restored.hapticFeedbackEnabled == false)
    }

    @Test func soundFeedbackEventsHaveStableSemantics() {
        #expect(AppFeedbackEvent.selection.sound == .tap)
        #expect(AppFeedbackEvent.impactLight.sound == .review)
        #expect(AppFeedbackEvent.success.sound == .success)
        #expect(AppFeedbackEvent.warning.sound == .warning)
        #expect(AppFeedbackEvent.error.sound == .error)
    }
}
