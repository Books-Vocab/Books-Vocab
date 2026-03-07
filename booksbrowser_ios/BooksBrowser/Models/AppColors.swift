//
//  AppColors.swift
//  BooksBrowser
//
//  集中化的語義色彩 Token 系統
//  ─────────────────────────────────────────────────────────────────────
//  設計哲學：莫蘭迪色系（Morandi Palette）— 明亮版
//    · 低飽和度（25-30%）但保持足夠亮度，不顯沉悶
//    · 色彩如同早晨窗邊透光的紗幔 — 柔和卻明確
//    · 紙張模擬 — 米白取代純白，深暖灰取代純黑
//  ─────────────────────────────────────────────────────────────────────

import SwiftUI

// MARK: - 莫蘭迪色彩 Token

enum AppColors {

    // ── 紙張背景色 ────────────────────────────────────────────────────
    static let paperLight = Color(red: 0.975, green: 0.978, blue: 0.982)
    static let paperSepia = Color(red: 0.98, green: 0.965, blue: 0.94)
    static let paperDark  = Color(red: 0.11, green: 0.106, blue: 0.098)

    // ── 主題強調色（莫蘭迪灰藍 · 明亮）────────────────────────────────
    // 如同淡水彩暈染的藍灰
    static let accentLight = Color(hue: 215/360, saturation: 0.28, brightness: 0.66)
    static let accentDark  = Color(hue: 215/360, saturation: 0.28, brightness: 0.70)

    // ── 翻譯文字色（栗棕 · 明亮）──────────────────────────────────────
    // 如同上好信箋上的棕色墨水
    static let translationLight = Color(hue: 22/360, saturation: 0.26, brightness: 0.62)
    static let translationDark  = Color(hue: 25/360, saturation: 0.25, brightness: 0.70)

    // ── 成功色（灰橄欖 · 明亮）────────────────────────────────────────
    // 如同風乾的鼠尾草葉
    static let savedLight = Color(hue: 152/360, saturation: 0.20, brightness: 0.60)
    static let savedDark  = Color(hue: 152/360, saturation: 0.20, brightness: 0.62)

    // ── 危險色（煙玫瑰 · 明亮）────────────────────────────────────────
    // 如同褪色的玫瑰花瓣
    static let destructiveLight = Color(hue: 355/360, saturation: 0.26, brightness: 0.66)
    static let destructiveDark  = Color(hue: 355/360, saturation: 0.25, brightness: 0.68)

    // ── 難度 Tier ─────────────────────────────────────────────────────
    static let tierCoreLight         = savedLight
    static let tierCoreDark          = savedDark
    static let tierIntermediateLight = Color(hue: 40/360, saturation: 0.28, brightness: 0.55)
    static let tierIntermediateDark  = Color(hue: 40/360, saturation: 0.25, brightness: 0.65)
    static let tierAdvancedLight     = translationLight
    static let tierAdvancedDark      = translationDark
    static let tierRareLight         = destructiveLight
    static let tierRareDark          = destructiveDark

    // ── App 全域 Tint（取代系統藍）────────────────────────────────────
    // 作為主題層的基礎 tint，實際注入由 AppTheme 決定
    static let tint = Color(hue: 215/360, saturation: 0.16, brightness: 0.52)

    // ── Glass-era Token ───────────────────────────────────────────────────
    static let glassClearBackground = Color.clear

    // ── Highlight Mark (Mochi-style 螢光筆) ──────────────────────────────
    static let highlightMark = Color(hue: 45/360, saturation: 0.50, brightness: 0.95)
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
        return scheme == .dark ? Color(hue: 0.05, saturation: 0.4, brightness: 0.8) : Color(hue: 0.05, saturation: 0.6, brightness: 0.7)
    }

    static func warning(_ scheme: ColorScheme) -> Color {
        return scheme == .dark ? Color(hue: 0.1, saturation: 0.6, brightness: 0.9) : Color(hue: 0.1, saturation: 0.8, brightness: 0.8)
    }

    static func tier(_ tier: String, scheme: ColorScheme) -> (color: Color, label: String) {
        switch tier {
        case "core":
            return (scheme == .dark ? tierCoreDark : tierCoreLight, "core")
        case "intermediate":
            return (scheme == .dark ? tierIntermediateDark : tierIntermediateLight, "inter")
        case "advanced":
            return (scheme == .dark ? tierAdvancedDark : tierAdvancedLight, "adv")
        case "rare":
            return (scheme == .dark ? tierRareDark : tierRareLight, "rare")
        default:
            return (Color.secondary, tier)
        }
    }
}

// MARK: - Web CSS Token

extension AppColors {
    static let vocabHighlightLightCSS = "linear-gradient(to top, hsla(215, 30%, 58%, 0.22) 35%, transparent 35%)"
    static let vocabHighlightDarkCSS  = "linear-gradient(to top, hsla(215, 28%, 70%, 0.20) 35%, transparent 35%)"
    static let vocabHighlightSepiaCSS = "linear-gradient(to top, hsla(22, 28%, 55%, 0.22) 35%, transparent 35%)"
}
