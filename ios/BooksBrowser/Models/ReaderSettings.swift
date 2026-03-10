//
//  ReaderSettings.swift
//  BooksBrowser
//
//  Created by Antigravity on 2026/2/25.
//

import SwiftUI
import ReadiumShared
import ReadiumNavigator
import Foundation

/// 閱讀字體型別
enum ReaderFont: String, CaseIterable, Identifiable {
    case serif   = "Garamond"
    case athelas = "Athelas"
    case sans    = "Sans"
    case mono    = "Mono"

    var id: String { self.rawValue }

    var family: FontFamily {
        switch self {
        case .serif:   return FontFamily("Cormorant Garamond")
        case .athelas: return FontFamily("Athelas")
        case .sans:    return FontFamily("Elms Sans")
        case .mono:    return FontFamily("Space Mono")
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
}

/// 翻譯面板顯示模式
enum TranslationPanelMode: String, CaseIterable, Identifiable {
    case glass = "Glass"  // 預設：iOS 26 glassEffect 風格
    case vocab = "Vocab"  // Vocabulary 組件風格（VocabSkin）

    var id: String { rawValue }

    var label: String {
        switch self {
        case .glass: return "Glass"
        case .vocab: return "Vocab"
        }
    }

    var icon: String {
        switch self {
        case .glass: return "rectangle.and.sparkles"
        case .vocab: return "character.book.closed"
        }
    }
}

struct ReaderViewConfiguration: Equatable {
    let paperColor: SwiftUI.Color
    let epubPreferences: EPUBPreferences
    let underlineOpacity: Double
    let showHitTestingDebug: Bool
    let swiftUIColorScheme: ColorScheme
    let translationPanelMode: TranslationPanelMode
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
    private let kTheme = "reader_settings_theme"
    private let kUnderlineOpacity = "reader_settings_underlineOpacity"
    private let kShowHitTestingDebug = "reader_settings_showHitTestingDebug"
    private let kTranslationPanelMode = "reader_settings_translationPanelMode"
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

    var theme: ReaderTheme = .sepia {
        didSet {
            defaults.set(theme.rawValue, forKey: kTheme)
            cloud.set(theme.rawValue, forKey: kTheme)
        }
    }

    var underlineOpacity: Double = 0.22 {
        didSet {
            defaults.set(underlineOpacity, forKey: kUnderlineOpacity)
            cloud.set(underlineOpacity, forKey: kUnderlineOpacity)
        }
    }

    var showHitTestingDebug: Bool = false {
        didSet { defaults.set(showHitTestingDebug, forKey: kShowHitTestingDebug) }
    }

    var translationPanelMode: TranslationPanelMode = .glass {
        didSet {
            defaults.set(translationPanelMode.rawValue, forKey: kTranslationPanelMode)
            cloud.set(translationPanelMode.rawValue, forKey: kTranslationPanelMode)
        }
    }

    private init() {
        // 優先從 iCloud KVS 讀取，fallback 到 UserDefaults
        if let raw = cloud.string(forKey: kFont) ?? defaults.string(forKey: kFont),
           let value = ReaderFont(rawValue: raw) {
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

        if let raw = cloud.string(forKey: kTheme) ?? defaults.string(forKey: kTheme),
           let value = ReaderTheme(rawValue: raw) {
            self.theme = value
        }

        if let cloudOpacity = cloud.double(forKey: kUnderlineOpacity) {
            self.underlineOpacity = cloudOpacity
        } else {
            let saved = defaults.double(forKey: kUnderlineOpacity)
            if saved > 0 || defaults.object(forKey: kUnderlineOpacity) != nil {
                self.underlineOpacity = saved
            }
        }

        self.showHitTestingDebug = defaults.bool(forKey: kShowHitTestingDebug)

        if let raw = cloud.string(forKey: kTranslationPanelMode) ?? defaults.string(forKey: kTranslationPanelMode),
           let value = TranslationPanelMode(rawValue: raw) {
            self.translationPanelMode = value
        }

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
        for key in keys {
            switch key {
            case kFont:
                if let raw = cloud.string(forKey: key), let value = ReaderFont(rawValue: raw) { font = value }
            case kFontSize:
                if let value = cloud.double(forKey: key) { fontSize = value }
            case kLineHeight:
                if let value = cloud.double(forKey: key) { lineHeight = value }
            case kTheme:
                if let raw = cloud.string(forKey: key), let value = ReaderTheme(rawValue: raw) { theme = value }
            case kUnderlineOpacity:
                if let value = cloud.double(forKey: key) { underlineOpacity = value }
            case kTranslationPanelMode:
                if let raw = cloud.string(forKey: key), let value = TranslationPanelMode(rawValue: raw) { translationPanelMode = value }
            default:
                break
            }
        }
    }
    
    // MARK: - Readium 轉換
    
    var paperColor: SwiftUI.Color {
        switch theme {
        case .light: return AppColors.paperLight
        case .sepia: return AppColors.paperSepia
        case .dark:  return AppColors.paperDark
        }
    }
    
    private var readiumColor: ReadiumNavigator.Color? {
        // 從 SwiftUI.Color 轉換為 UIColor 再轉換為 ReadiumNavigator.Color
        ReadiumNavigator.Color(color: paperColor)
    }
    
    var epubPreferences: EPUBPreferences {
        EPUBPreferences(
            backgroundColor: readiumColor,
            fontFamily: font.family,
            fontSize: fontSize,
            lineHeight: lineHeight,
            publisherStyles: false,
            theme: theme.theme
        )
    }
    
    /// SwiftUI 全域 color scheme
    var swiftUIColorScheme: ColorScheme {
        switch theme {
        case .light, .sepia: return .light
        case .dark: return .dark
        }
    }

    var viewConfiguration: ReaderViewConfiguration {
        ReaderViewConfiguration(
            paperColor: paperColor,
            epubPreferences: epubPreferences,
            underlineOpacity: underlineOpacity,
            showHitTestingDebug: showHitTestingDebug,
            swiftUIColorScheme: swiftUIColorScheme,
            translationPanelMode: translationPanelMode
        )
    }
}
