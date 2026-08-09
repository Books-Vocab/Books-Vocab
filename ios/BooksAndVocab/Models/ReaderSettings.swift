#if os(iOS)
//
//  ReaderSettings.swift
//  Books & Vocab
//
//  Created by Antigravity on 2026/2/25.
//

import SwiftUI
import ReadiumShared
import ReadiumNavigator
import Foundation

/// 閱讀字體型別
enum ReaderFont: String, CaseIterable, Identifiable {
    case serif      = "Garamond"
    case crimsonPro = "CrimsonPro"
    case sans       = "Sans"
    case mono       = "Mono"

    var id: String { self.rawValue }

    /// Decode a persisted rawValue, mapping legacy keys to their current case.
    /// 舊儲存值 "Athelas"（Apple OS 字體，已替換為 Crimson Pro）必須能解到 .crimsonPro，
    /// 否則既有使用者的閱讀字體設定會默默退回預設。
    static func decode(_ raw: String) -> ReaderFont? {
        if raw == "Athelas" { return .crimsonPro }  // legacy alias
        return ReaderFont(rawValue: raw)
    }

    /// WebView 端的 CSS family。`buildFontFaceCSS()` 用同名 `@font-face` 把
    /// bundle 裡的 TTF 餵給 WKWebView。
    var family: FontFamily {
        switch self {
        case .serif:      return FontFamily("Cormorant Garamond")
        case .crimsonPro: return FontFamily("Crimson Pro")
        case .sans:       return FontFamily("Elms Sans")
        case .mono:       return FontFamily("Space Mono")
        }
    }

    /// 原生端的**同一批字檔**，給 `Font.custom(_:size:)`。閱讀設定的即時預覽
    /// 靠這個跟閱讀器用到同一個字體檔（`ios/BooksAndVocab/Resources/*.ttf`，
    /// 已列在 Info.plist 的 UIAppFonts）。
    ///
    /// **必須是 PostScript name，不是檔名** —— Crimson Pro 的 PostScript name 是
    /// `CrimsonProRoman-Regular`（檔名卻是 `CrimsonPro-Regular.ttf`）。名字給錯時
    /// `Font.custom` 不會報錯，只會靜靜退回系統字體，預覽就變成在騙人。
    /// 這四個值是用 fontTools 讀 name table (nameID 6) 量出來的。
    var previewFontName: String {
        switch self {
        case .serif:      return "CormorantGaramond-Regular"
        case .crimsonPro: return "CrimsonProRoman-Regular"
        case .sans:       return "ElmsSans-Regular"
        case .mono:       return "SpaceMono-Regular"
        }
    }

    /// 字體選單顯示名（走 L10n；品牌名為 ASCII 字面，鍵以中性 key 命名以利翻譯覆寫）
    var displayName: String {
        switch self {
        case .serif:      return L10n.string("reader.font.garamond")
        case .crimsonPro: return L10n.string("reader.font.crimsonPro")
        case .sans:       return L10n.string("reader.font.sans")
        case .mono:       return L10n.string("reader.font.mono")
        }
    }
}

/// 閱讀主題型別 — 紙張模擬 + 生物鐘哲學
enum ReaderTheme: String, CaseIterable, Identifiable {
    case light = "Light"
    case sepia = "Sepia"
    case dark  = "Dark"

    var id: String { self.rawValue }

    var theme: Theme {
        switch self {
        case .light: return .light
        case .sepia: return .sepia
        case .dark:  return .dark
        }
    }

    var icon: String {
        switch self {
        case .light: return "sun.max.fill"
        case .sepia: return "book.fill"
        case .dark:  return "moon.stars.fill"
        }
}

    /// 紙色 —— App 覆寫掉 Readium 的 `--RS__backgroundColor`，經
    /// `EPUBPreferences.backgroundColor` 送進 WebView。
    var paperColor: SwiftUI.Color {
        switch self {
        case .light: return AppColors.paperLight
        case .sepia: return AppColors.paperSepia
        case .dark:  return AppColors.paperDark
        }
    }

    /// 墨色 —— App **沒有**覆寫，沿用 Readium 主題的 `--RS__textColor`。
    /// 與 `paperColor` 成對放在這裡，新增主題時兩個都得填，漏一個編不過。
    var inkColor: SwiftUI.Color {
        switch self {
        case .light, .sepia: return AppColors.readerInkLight
        case .dark:          return AppColors.readerInkDark
        }
    }
}

struct ReaderViewConfiguration: Equatable {
    let paperColor: SwiftUI.Color
    let epubPreferences: EPUBPreferences
    let highlightPreferences: VocabHighlightPreferences
    let showHitTestingDebug: Bool
    let swiftUIColorScheme: ColorScheme

    var underlineOpacity: Double { highlightPreferences.opacity }

    var contentStyleCSS: String {
        ReaderContentStyleFactory.make(highlightPreferences: highlightPreferences).css()
    }

    init(
        paperColor: SwiftUI.Color,
        epubPreferences: EPUBPreferences,
        underlineOpacity: Double? = nil,
        highlightPreferences: VocabHighlightPreferences = .default,
        showHitTestingDebug: Bool,
        swiftUIColorScheme: ColorScheme
    ) {
        self.paperColor = paperColor
        self.epubPreferences = epubPreferences
        var resolvedHighlight = highlightPreferences
        if let underlineOpacity {
            resolvedHighlight.opacity = underlineOpacity
        }
        self.highlightPreferences = resolvedHighlight
        self.showHitTestingDebug = showHitTestingDebug
        self.swiftUIColorScheme = swiftUIColorScheme
    }
}

/// 閱讀器偏好設定模型 — 全域單例，直接讀寫 UserDefaults 並同步至 iCloud KVS
@Observable
final class ReaderSettings {
    static let shared = ReaderSettings()

    private let defaults = UserDefaults.standard
    private let cloud = CloudPreferencesSync.shared
    private let kFont = "reader_settings_font"
    private let kFontSize = "reader_settings_fontSize"
    private let kLineHeight = "reader_settings_lineHeight"
    private let kUnderlineOpacity = "reader_settings_underlineOpacity"
    private let kVocabHighlightColorPreset = "vocab_highlight_colorPreset"
    private let kVocabHighlightOpacity = "vocab_highlight_opacity"
    private let kShowHitTestingDebug = "reader_settings_showHitTestingDebug"
    private let kScrollMode = "reader_settings_scrollMode"
    private var cloudObserver: NSObjectProtocol?

    var font: ReaderFont = .serif {
        didSet {
            defaults.set(font.rawValue, forKey: kFont)
            cloud.set(font.rawValue, forKey: kFont)
        }
    }

    var fontSize: Double = 1.0 {
        didSet {
            defaults.set(fontSize, forKey: kFontSize)
            cloud.set(fontSize, forKey: kFontSize)
        }
    }

    var lineHeight: Double = 1.4 {
        didSet {
            defaults.set(lineHeight, forKey: kLineHeight)
            cloud.set(lineHeight, forKey: kLineHeight)
        }
    }

    /// 翻頁(false) / 連續捲動(true)。iCloud 以 Double 編碼同步
    /// （CloudPreferencesSync 僅 String/Double，Bool 走 0.0/1.0）。
    var scrollMode: Bool = false {
        didSet {
            defaults.set(scrollMode, forKey: kScrollMode)
            cloud.set(scrollMode ? 1.0 : 0.0, forKey: kScrollMode)
        }
    }

    /// 閱讀器主題 — 由全域 AppAppearanceStore 驅動，不再獨立儲存。
    /// 需要 systemColorScheme 以正確解析 `.system` 模式。
    func resolvedTheme(systemColorScheme: ColorScheme) -> ReaderTheme {
        AppAppearanceStore.shared.resolvedReaderTheme(systemColorScheme: systemColorScheme)
    }

    var underlineOpacity: Double = 0.22 {
        didSet {
            defaults.set(underlineOpacity, forKey: kUnderlineOpacity)
            defaults.set(underlineOpacity, forKey: kVocabHighlightOpacity)
            cloud.set(underlineOpacity, forKey: kUnderlineOpacity)
            cloud.set(underlineOpacity, forKey: kVocabHighlightOpacity)
        }
    }

    var vocabHighlightColorPreset: VocabHighlightColorPreset = .paper {
        didSet {
            defaults.set(vocabHighlightColorPreset.rawValue, forKey: kVocabHighlightColorPreset)
            cloud.set(vocabHighlightColorPreset.rawValue, forKey: kVocabHighlightColorPreset)
        }
    }

    var vocabHighlightPreferences: VocabHighlightPreferences {
        VocabHighlightPreferences(
            colorPreset: vocabHighlightColorPreset,
            opacity: underlineOpacity
        )
    }

    var showHitTestingDebug: Bool = false {
        didSet { defaults.set(showHitTestingDebug, forKey: kShowHitTestingDebug) }
    }

    private init() {
        // 優先從 iCloud KVS 讀取，fallback 到 UserDefaults
        if let raw = cloud.string(forKey: kFont) ?? defaults.string(forKey: kFont),
           let value = ReaderFont.decode(raw) {
            self.font = value
        }

        if let cloudSize = cloud.double(forKey: kFontSize) {
            self.fontSize = cloudSize
        } else {
            let saved = defaults.double(forKey: kFontSize)
            if saved > 0 { self.fontSize = saved }
        }

        if let cloudHeight = cloud.double(forKey: kLineHeight) {
            self.lineHeight = cloudHeight
        } else {
            let saved = defaults.double(forKey: kLineHeight)
            if saved > 0 { self.lineHeight = saved }
        }

        if let cloudScroll = cloud.double(forKey: kScrollMode) {
            self.scrollMode = cloudScroll > 0.5
        } else {
            self.scrollMode = defaults.bool(forKey: kScrollMode)
        }

        let cloudPreset = cloud.string(forKey: kVocabHighlightColorPreset)
        let savedPreset = defaults.string(forKey: kVocabHighlightColorPreset)
        let cloudOpacity = cloud.double(forKey: kVocabHighlightOpacity)
        let savedOpacity = defaults.object(forKey: kVocabHighlightOpacity) != nil
            ? defaults.double(forKey: kVocabHighlightOpacity)
            : nil
        let legacyCloudOpacity = cloud.double(forKey: kUnderlineOpacity)
        let legacySavedOpacity = defaults.object(forKey: kUnderlineOpacity) != nil
            ? defaults.double(forKey: kUnderlineOpacity)
            : nil
        let resolvedHighlight = VocabHighlightPreferences.resolve(
            storedPresetRaw: cloudPreset ?? savedPreset,
            storedOpacity: cloudOpacity ?? savedOpacity,
            legacyOpacity: legacyCloudOpacity ?? legacySavedOpacity
        )
        self.vocabHighlightColorPreset = resolvedHighlight.colorPreset
        self.underlineOpacity = resolvedHighlight.opacity

        if cloudOpacity == nil && savedOpacity == nil {
            defaults.set(resolvedHighlight.opacity, forKey: kVocabHighlightOpacity)
            cloud.set(resolvedHighlight.opacity, forKey: kVocabHighlightOpacity)
        }
        if cloudPreset == nil && savedPreset == nil {
            defaults.set(resolvedHighlight.colorPreset.rawValue, forKey: kVocabHighlightColorPreset)
            cloud.set(resolvedHighlight.colorPreset.rawValue, forKey: kVocabHighlightColorPreset)
        }

        self.showHitTestingDebug = defaults.bool(forKey: kShowHitTestingDebug)

        cloudObserver = NotificationCenter.default.addObserver(
            forName: NSUbiquitousKeyValueStore.didChangeExternallyNotification,
            object: NSUbiquitousKeyValueStore.default,
            queue: .main
        ) { [weak self] notification in
            self?.handleCloudChange(notification)
        }
    }

    deinit {
        if let observer = cloudObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    private func handleCloudChange(_ notification: Notification) {
        guard let keys = notification.userInfo?[NSUbiquitousKeyValueStoreChangedKeysKey] as? [String] else { return }
        let hasNewHighlightOpacity = keys.contains(kVocabHighlightOpacity)
        for key in keys {
            switch key {
            // Echo guard: only apply when the inbound value differs from current,
            // else didSet re-writes to cloud and forces an echo flush. Mirrors
            // AppLanguage.swift / AppAppearanceMode.swift `value != selection`.
            case kFont:
                if let raw = cloud.string(forKey: key), let value = ReaderFont.decode(raw), value != font { font = value }
            case kFontSize:
                if let value = cloud.double(forKey: key), value != fontSize { fontSize = value }
            case kLineHeight:
                if let value = cloud.double(forKey: key), value != lineHeight { lineHeight = value }
            case kScrollMode:
                if let value = cloud.double(forKey: key) { let v = value > 0.5; if v != scrollMode { scrollMode = v } }
            case kUnderlineOpacity where !hasNewHighlightOpacity:
                if let value = cloud.double(forKey: key), value != underlineOpacity { underlineOpacity = value }
            case kVocabHighlightOpacity:
                if let value = cloud.double(forKey: key), value != underlineOpacity { underlineOpacity = value }
            case kVocabHighlightColorPreset:
                if let raw = cloud.string(forKey: key),
                   let value = VocabHighlightColorPreset(rawValue: raw),
                   value != vocabHighlightColorPreset {
                    vocabHighlightColorPreset = value
                }
            default:
                break
            }
        }
    }

    // MARK: - Readium 轉換

    func viewConfiguration(systemColorScheme: ColorScheme) -> ReaderViewConfiguration {
        let theme = resolvedTheme(systemColorScheme: systemColorScheme)
        let paper = theme.paperColor
        return ReaderViewConfiguration(
            paperColor: paper,
            epubPreferences: EPUBPreferences(
                backgroundColor: ReadiumNavigator.Color(color: paper),
                fontFamily: font.family,
                fontSize: fontSize,
                lineHeight: lineHeight,
                publisherStyles: false,
                scroll: scrollMode,
                theme: theme.theme
            ),
            underlineOpacity: underlineOpacity,
            highlightPreferences: vocabHighlightPreferences,
            showHitTestingDebug: showHitTestingDebug,
            swiftUIColorScheme: theme == .dark ? .dark : .light
        )
    }
}
#endif
