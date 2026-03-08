//
//  ReaderSettings.swift
//  BooksBrowser
//
//  Created by Antigravity on 2026/2/25.
//

import SwiftUI
import ReadiumShared
import ReadiumNavigator

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

/// 閱讀器偏好設定模型 — 全域單例，直接讀寫 UserDefaults
@Observable
final class ReaderSettings {
    static let shared = ReaderSettings()
    
    private let defaults = UserDefaults.standard
    private let kFont = "reader_settings_font"
    private let kFontSize = "reader_settings_fontSize"
    private let kLineHeight = "reader_settings_lineHeight"
    private let kTheme = "reader_settings_theme"
    private let kUnderlineOpacity = "reader_settings_underlineOpacity"
    private let kShowHitTestingDebug = "reader_settings_showHitTestingDebug"
    private let kTranslationPanelMode = "reader_settings_translationPanelMode"
    
    var font: ReaderFont = .serif {
        didSet { defaults.set(font.rawValue, forKey: kFont) }
    }
    
    var fontSize: Double = 1.0 {
        didSet { defaults.set(fontSize, forKey: kFontSize) }
    }
    
    var lineHeight: Double = 1.4 {
        didSet { defaults.set(lineHeight, forKey: kLineHeight) }
    }
    
    var theme: ReaderTheme = .sepia {
        didSet { defaults.set(theme.rawValue, forKey: kTheme) }
    }
    
    var underlineOpacity: Double = 0.22 {
        didSet { defaults.set(underlineOpacity, forKey: kUnderlineOpacity) }
    }
    
    
    var showHitTestingDebug: Bool = false {
        didSet { defaults.set(showHitTestingDebug, forKey: kShowHitTestingDebug) }
    }

    var translationPanelMode: TranslationPanelMode = .glass {
        didSet { defaults.set(translationPanelMode.rawValue, forKey: kTranslationPanelMode) }
    }
    
    private init() {
        // Load persisted values from UserDefaults
        if let raw = defaults.string(forKey: kFont),
           let value = ReaderFont(rawValue: raw) {
            self.font = value
        }
        let savedFontSize = defaults.double(forKey: kFontSize)
        if savedFontSize > 0 { self.fontSize = savedFontSize }
        
        let savedLineHeight = defaults.double(forKey: kLineHeight)
        if savedLineHeight > 0 { self.lineHeight = savedLineHeight }
        
        if let raw = defaults.string(forKey: kTheme),
           let value = ReaderTheme(rawValue: raw) {
            self.theme = value
        }
        
        let savedOpacity = defaults.double(forKey: kUnderlineOpacity)
        if savedOpacity > 0 || defaults.object(forKey: kUnderlineOpacity) != nil {
            self.underlineOpacity = savedOpacity
        }
        

        self.showHitTestingDebug = defaults.bool(forKey: kShowHitTestingDebug)

        if let raw = defaults.string(forKey: kTranslationPanelMode),
           let value = TranslationPanelMode(rawValue: raw) {
            self.translationPanelMode = value
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
