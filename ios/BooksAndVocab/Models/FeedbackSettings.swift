import Foundation
import Observation
import SwiftUI

/// Device-local preferences for short UI feedback.
///
/// This store intentionally does not control TTS or Podcast playback. Those are
/// content audio and keep their existing, feature-specific settings.
@Observable
final class FeedbackSettingsStore {
    static let shared = FeedbackSettingsStore()

    private enum Keys {
        static let soundFeedbackEnabled = "feedback_sound_enabled"
        static let hapticFeedbackEnabled = "feedback_haptic_enabled"
    }

    private let defaults: UserDefaults
    private(set) var soundFeedbackEnabled: Bool
    private(set) var hapticFeedbackEnabled: Bool

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.soundFeedbackEnabled = defaults.object(forKey: Keys.soundFeedbackEnabled) as? Bool ?? false
        self.hapticFeedbackEnabled = defaults.object(forKey: Keys.hapticFeedbackEnabled) as? Bool ?? true
    }

    func setSoundFeedbackEnabled(_ value: Bool) {
        soundFeedbackEnabled = value
        defaults.set(value, forKey: Keys.soundFeedbackEnabled)
    }

    func setHapticFeedbackEnabled(_ value: Bool) {
        hapticFeedbackEnabled = value
        defaults.set(value, forKey: Keys.hapticFeedbackEnabled)
    }
}

private struct FeedbackSettingsStoreKey: EnvironmentKey {
    static let defaultValue: FeedbackSettingsStore = .shared
}

extension EnvironmentValues {
    var feedbackSettingsStore: FeedbackSettingsStore {
        get { self[FeedbackSettingsStoreKey.self] }
        set { self[FeedbackSettingsStoreKey.self] = newValue }
    }
}
