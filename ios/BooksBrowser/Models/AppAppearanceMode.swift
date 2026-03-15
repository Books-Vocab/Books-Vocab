import SwiftUI

enum AppAppearanceMode: String, CaseIterable, Identifiable {
    case system
    case light
    case sepia
    case dark

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .system: return "跟隨系統"
        case .light: return "淺色"
        case .sepia: return "暖紙"
        case .dark: return "深色"
        }
    }

    var colorScheme: ColorScheme? {
        switch self {
        case .system: return nil
        case .light, .sepia: return .light
        case .dark: return .dark
        }
    }

    var icon: String {
        if self == .system { return "circle.lefthalf.filled" }
        return readerTheme.icon
    }

    /// 對應的 ReaderTheme（供 Readium 使用）；system 時 fallback light，實際由 resolved 決定
    var readerTheme: ReaderTheme {
        switch self {
        case .system: return .light
        case .light: return .light
        case .sepia: return .sepia
        case .dark: return .dark
        }
    }

    /// 從 ReaderTheme 反向映射（Reader 設定面板用）
    init(from readerTheme: ReaderTheme) {
        switch readerTheme {
        case .light: self = .light
        case .sepia: self = .sepia
        case .dark: self = .dark
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

    /// 解析最終的 ReaderTheme — system 模式依賴外部提供的 systemColorScheme
    func resolvedReaderTheme(systemColorScheme: ColorScheme) -> ReaderTheme {
        if selection == .system {
            return systemColorScheme == .dark ? .dark : .light
        }
        return selection.readerTheme
    }

    func setAppearance(_ mode: AppAppearanceMode) {
        guard selection != mode else { return }
        selection = mode
        defaults.set(mode.rawValue, forKey: Keys.selectedAppearance)
        cloud.set(mode.rawValue, forKey: Keys.selectedAppearance)
    }
}
