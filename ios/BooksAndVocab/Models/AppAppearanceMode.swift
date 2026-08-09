import SwiftUI

enum AppAppearanceMode: String, CaseIterable, Identifiable {
    case system
    case light
    case sepia
    case dark

    var id: String { rawValue }

    var titleKey: String {
        switch self {
        case .system: return L10n.string("跟隨系統")
        case .light: return L10n.string("淺色")
        case .sepia: return L10n.string("暖紙")
        case .dark: return L10n.string("深色")
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
        switch self {
        case .system: return "circle.lefthalf.filled"
        case .light: return "sun.max"
        case .sepia: return "book"
        case .dark: return "moon"
        }
    }

    #if os(iOS)
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
    #endif
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

    #if os(iOS)
    /// 解析最終的 ReaderTheme — system 模式依賴外部提供的 systemColorScheme
    func resolvedReaderTheme(systemColorScheme: ColorScheme) -> ReaderTheme {
        if selection == .system {
            return systemColorScheme == .dark ? .dark : .light
        }
        return selection.readerTheme
    }
    #endif

    func setAppearance(_ mode: AppAppearanceMode) {
        guard selection != mode else { return }
        selection = mode
        defaults.set(mode.rawValue, forKey: Keys.selectedAppearance)
        cloud.set(mode.rawValue, forKey: Keys.selectedAppearance)
    }

    private init(previewSelection: AppAppearanceMode) {
        self.defaults = UserDefaults(suiteName: "preview.appearance") ?? .standard
        self.selection = previewSelection
    }

    static let preview = AppAppearanceStore(previewSelection: .system)
}

// MARK: - Presentation 邊界

/// Sheet / fullScreenCover 是**另一個 presentation host**。SwiftUI 只在「呈現的
/// 那一刻」把當下的 interface style 播種給它自己的 hosting controller；之後 root
/// （`BooksAndVocabApp` 那一句 `.preferredColorScheme`）再改，**已經在畫面上的
/// presentation 不會被重新播種**。
///
/// 於是同一個 presentation 裡會並存兩套配色：吃 SwiftUI 環境值畫的（`.tint`、
/// `appSkin` 色票、自繪卡片）當場換新，吃系統色畫的（原生 `Form` / `List` 的背景
/// 與標籤、nav bar）停在呈現當下那一套。APP-20260809-f1b8cb 就是這個 ——
/// 在閱讀設定頁選深色的當下，近白的 `tintDark` 畫在還是淺色的 `Form` 上直接消失。
///
/// **它不是單向的**：判準是「離開這個 presentation 被呈現時的那個外觀」，不是往
/// 哪個方向切。也不是 pop 再 push 能救的 —— 要整個 presentation 被關掉重開。
///
/// 這與 `settingsSheet` 早就在做的「`@EnvironmentObject` 不跨 sheet 邊界，所以在
/// 邊界 re-inject」是同一件事的兩半：**環境要在邊界重新宣告一次**。
private struct AppResolvedColorSchemeKey: EnvironmentKey {
    static let defaultValue: ColorScheme? = nil
}

extension EnvironmentValues {
    /// App 選定的外觀**解析後**的具體 light / dark —— `.system` 已經對照裝置解析過。
    ///
    /// 由 `AppThemeContainer` 在 app 根寫入。要在那裡解析而不是在 sheet 裡就地解析，
    /// 是因為**沒有這個修法時** sheet 內讀到的 `\.colorScheme` 就是那個被凍住的舊值
    /// （有了修法之後它已經被本鍵餵成正確值，但那是結果，不能拿來當自己的來源 ——
    /// 就地解析等於讓它自己餵自己）。（根那裡讀到的也不是「裝置的」scheme 而是
    /// 視窗的；它之所以夠用靠的是 `??` 短路，條件寫在 `AppThemeContainer` 那一行。）
    ///
    /// 為什麼一定要**具體值**而不能直接用 `AppAppearanceStore.resolvedColorScheme`：
    /// 後者在 `.system` 時是 `nil`，而 `preferredColorScheme(nil)` 的語意是「我不表態」
    /// —— 不表態沒有辦法把一個已經被播種成淺色的 sheet 拉回深色。實測：外觀從
    /// 「淺色」改成「跟隨系統」（裝置深色）時，開著的 sheet 會整頁留在淺色。
    var appResolvedColorScheme: ColorScheme? {
        get { self[AppResolvedColorSchemeKey.self] }
        set { self[AppResolvedColorSchemeKey.self] = newValue }
    }
}

private struct AppAppearanceSchemeModifier: ViewModifier {
    /// 讀 value-based environment 而不是 `@EnvironmentObject`：前者跨得過 sheet
    /// 邊界，而且改變時會即時傳進**已經呈現**的 sheet（那正是 tint 會當場變色的
    /// 同一條路）。
    @Environment(\.appResolvedColorScheme) private var resolvedScheme

    func body(content: Content) -> some View {
        content.preferredColorScheme(resolvedScheme)
    }
}

extension View {
    /// 掛在 sheet / fullScreenCover 的**內容根**上，重新宣告 app 選定的外觀。
    ///
    /// 冪等：它宣告的永遠是 root 已經宣告過的同一個值，只是讓已呈現的
    /// presentation 也跟著改。走 `toastSheet` / `platformFullScreenCover` 的呼叫端
    /// 不必自己寫，那兩個 seam 已經寫了；自己開原生 presentation 的地方要自己寫，
    /// 由 `SheetAppearanceBoundaryTests` 釘住。
    func appAppearanceScheme() -> some View {
        modifier(AppAppearanceSchemeModifier())
    }
}
