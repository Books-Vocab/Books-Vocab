//
//  AppColors.swift
//  BooksBrowser
//
//  ⚠️  使用範圍：Reader 功能 + 全域 UI（ErrorBanner、App tint）
//  ─────────────────────────────────────────────────────────────────────
//  此檔案 *不是* Vocabulary UI 的顏色來源。
//  Vocabulary 功能的所有顏色請透過 @Environment(\.appSkin) 取得，
//  其背後由 AppTheme → AppSkin.themed() 組裝而成。
//
//  設計哲學：Notion-inspired Palette + Morandi 強調色
//    · 表面近白／中性深灰 — 純淨、扁平，不靠重陰影靠 border 分層
//    · 暖近黑文字（#37352F）取代純黑，承襲 Notion 的溫潤閱讀感
//    · 強調色採 Morandi grey-blue（accent #4D7396 / hero #3D5F82）
//      — 取代原本 Notion product 藍 #2383E2，降飽和度貼合書卷氣調性
//    · 對比採分級制：正文 ≥4.5:1、metadata ≥3:1、裝飾 ~2.5:1
//  ─────────────────────────────────────────────────────────────────────
//  顏色分組（依使用方）
//    [Reader]  paper*, highlightMarkCSS（ReaderSettings 使用）
//    [Reader]  accent, saved, destructive, warning（TranslationPanel 使用）
//    [Global]  tint（BooksBrowserApp 注入 SwiftUI tint）
//  ─────────────────────────────────────────────────────────────────────

import SwiftUI

// MARK: - Notion-inspired 色彩 Token（Reader ＆ 全域）

enum AppColors {

    // ── 紙張背景色 ────────────────────────────────────────────────────
    static let paperLight     = Color(red: 0.984, green: 0.980, blue: 0.973)
    static let paperSepia     = Color(red: 0.98, green: 0.965, blue: 0.94)
    static let paperSepiaDeep = Color(red: 0.96, green: 0.93, blue: 0.87)
    static let paperDark      = Color(red: 0.098, green: 0.098, blue: 0.098)

    // ── 主題強調色（Morandi grey-blue · 取代 Notion 連結藍）─────────────
    // light: #4D7396（~4.99:1 on 白卡） · 由原 #3078A1 降飽和度至 ~36%
    // dark:  #85A4C2（~6.77:1 on 深灰頁面 #191919） · 由原 #5E9FD0 降飽和度至 ~30%
    // 實測對比由 BooksBrowserTests/WCAGContrastTests.swift 鎖住。
    static let accentLight = Color(red: 0.302, green: 0.451, blue: 0.588)
    static let accentDark  = Color(red: 0.522, green: 0.643, blue: 0.761)

    // ── Brand Hero（Morandi indigo · 主行動色 CTA）────────────────────
    // 用於主要 CTA、登入、Today Review 啟動鍵 — 比 accent 更深以維持 prominence
    // light: #3D5F82 — 白字對比 ~6.65:1 ✓ AA pass
    // dark:  #4A6E91 — 白字對比 ~5.34:1 ✓ AA pass（取代舊 #2383E2 的 4.02:1 fail）
    static let brandHeroLight = Color(red: 0.239, green: 0.373, blue: 0.510) // #3D5F82
    static let brandHeroDark  = Color(red: 0.290, green: 0.431, blue: 0.569) // #4A6E91

    // ── On-Brand-Hero 前景 ────────────────────────────────────────────
    // brandHero 系背景上的前景文字/圖示色。白色於 brandHeroLight 上 ~6.5:1（WCAG AA ✓）。
    static let onBrandHero = Color.white

    // ── 資訊色（Morandi blue · 與 accent 同色系）──────────────────────
    // 用於 info banner、提示訊息、tooltip 等中性提示
    static let infoLight = Color(red: 0.302, green: 0.451, blue: 0.588)
    static let infoDark  = Color(red: 0.522, green: 0.643, blue: 0.761)

    // ── 翻譯文字色（暖棕墨水）─────────────────────────────────────────
    // Reader 翻譯面板專用，與正文區隔
    static let translationLight = Color(hue: 22/360, saturation: 0.26, brightness: 0.62)
    static let translationDark  = Color(hue: 25/360, saturation: 0.25, brightness: 0.70)

    // ── 成功色（Notion 綠）────────────────────────────────────────────
    // light: #3B7A3B（~4.8:1）  dark: #6FB36F（~6.6:1）
    static let savedLight = Color(red: 0.231, green: 0.478, blue: 0.231)
    static let savedDark  = Color(red: 0.435, green: 0.702, blue: 0.435)

    // ── 危險色（Notion 紅）────────────────────────────────────────────
    // light: #B5403A（~5.2:1）  dark: #E0726B（~5.3:1）
    static let destructiveLight = Color(red: 0.710, green: 0.251, blue: 0.227)
    static let destructiveDark  = Color(red: 0.878, green: 0.447, blue: 0.420)

    // ── 警告色（Notion 琥珀）──────────────────────────────────────────
    // light: #8C6014（~5.1:1）  dark: #D9A441（~7.3:1）
    static let warningLight = Color(red: 0.549, green: 0.376, blue: 0.078)
    static let warningDark  = Color(red: 0.851, green: 0.643, blue: 0.255)

    // ── App 全域 Tint（取代系統藍）────────────────────────────────────
    // 作為主題層的基礎 tint，與 accentLight 同色（Morandi grey-blue #4D7396）
    static let tint = Color(red: 0.302, green: 0.451, blue: 0.588)

    // ── 暖中性棕（Preview 場景頁底漸層用）────────────────────────────────
    static let warmNeutral = Color(hue: 30/360, saturation: 0.18, brightness: 0.62)

    // ── Highlight Mark (paper-style 螢光筆) ──────────────────────────────
    static let highlightMark = Color(hue: 45/360, saturation: 0.50, brightness: 0.95)
}

enum AppBrandColors {
    static let googleRed = Color(red: 0.87, green: 0.19, blue: 0.19)
    static let appleBlack = Color.black
}

// MARK: - 環境感知

extension AppColors {
    static func theme(_ scheme: ColorScheme) -> AppTheme {
        AppTheme.resolve(for: scheme)
    }

    static func accent(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? accentDark : accentLight
    }

    static func translation(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? translationDark : translationLight
    }

    static func saved(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? savedDark : savedLight
    }

    static func destructive(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? destructiveDark : destructiveLight
    }

    static func warning(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? warningDark : warningLight
    }

    static func brandHero(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? brandHeroDark : brandHeroLight
    }

    static func info(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? infoDark : infoLight
    }
}

// MARK: - Web CSS Token

extension AppColors {
    // Morandi grey-blue (hue 212, 與 accentLight/Dark 同色相)
    static let vocabHighlightLightCSS = "linear-gradient(to top, hsla(212, 32%, 47%, 0.20) 35%, transparent 35%)"
    static let vocabHighlightDarkCSS  = "linear-gradient(to top, hsla(210, 32%, 64%, 0.20) 35%, transparent 35%)"
    static let vocabHighlightSepiaCSS = "linear-gradient(to top, hsla(22, 28%, 55%, 0.22) 35%, transparent 35%)"
}
