import SwiftUI

enum AppAppearanceMode: String, CaseIterable, Identifiable {
    case system
    case light
    case dark

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .system: return "跟隨系統"
        case .light: return "淺色"
        case .dark: return "深色"
        }
    }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light: return .light
        case .dark: return .dark
        }
    }
}

final class AppAppearanceStore: ObservableObject {
    static let shared = AppAppearanceStore()

    private enum Keys {
        static let selectedAppearance = "app_appearance_selection"
    }

    @Published private(set) var selection: AppAppearanceMode

    private let defaults: UserDefaults
    private let cloud = CloudPreferencesSync.shared

    private init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        let raw = cloud.string(forKey: Keys.selectedAppearance) ?? defaults.string(forKey: Keys.selectedAppearance)
        if let raw, let selection = AppAppearanceMode(rawValue: raw) {
            self.selection = selection
        } else {
            self.selection = .system
        }
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleCloudChange(_:)),
            name: NSUbiquitousKeyValueStore.didChangeExternallyNotification,
            object: NSUbiquitousKeyValueStore.default
        )
    }

    deinit {
        NotificationCenter.default.removeObserver(self)
    }

    @objc private func handleCloudChange(_ notification: Notification) {
        guard let keys = notification.userInfo?[NSUbiquitousKeyValueStoreChangedKeysKey] as? [String],
              keys.contains(Keys.selectedAppearance),
              let raw = cloud.string(forKey: Keys.selectedAppearance),
              let value = AppAppearanceMode(rawValue: raw),
              value != selection
        else { return }
        DispatchQueue.main.async { self.selection = value }
    }

    var resolvedColorScheme: ColorScheme? {
        selection.colorScheme
    }

    func setAppearance(_ mode: AppAppearanceMode) {
        guard selection != mode else { return }
        selection = mode
        defaults.set(mode.rawValue, forKey: Keys.selectedAppearance)
        cloud.set(mode.rawValue, forKey: Keys.selectedAppearance)
    }
}
