import Foundation
import Observation
import SwiftUI

@Observable
final class AutoSyncSettingsStore {
    static let shared = AutoSyncSettingsStore()
    static let threshold = 5

    private enum Keys {
        static let enabled = "auto_sync_enabled"
    }

    private let defaults: UserDefaults
    private(set) var isEnabled: Bool

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        self.isEnabled = defaults.bool(forKey: Keys.enabled)
    }

    func setEnabled(_ value: Bool) {
        isEnabled = value
        defaults.set(value, forKey: Keys.enabled)
    }
}

// MARK: - Environment

private struct AutoSyncSettingsStoreKey: EnvironmentKey {
    static let defaultValue: AutoSyncSettingsStore = .shared
}

extension EnvironmentValues {
    var autoSyncSettingsStore: AutoSyncSettingsStore {
        get { self[AutoSyncSettingsStoreKey.self] }
        set { self[AutoSyncSettingsStoreKey.self] = newValue }
    }
}
