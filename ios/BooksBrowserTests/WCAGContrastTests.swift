//
//  WCAGContrastTests.swift
//  BooksBrowserTests
//
//  Guards against regressing the palette below WCAG AA. Every accent /
//  hero color shifted in the Morandi refinement (Phase 1) is asserted
//  against its documented contrast target. If you tune palette values,
//  update both the constant and the expected ratio here in the same PR.
//
//  Why this exists: AppColors.swift only documents target ratios in
//  comments. Without a test, future palette tweaks can silently push
//  text/CTA contrast below 4.5:1.
//

import Testing
import SwiftUI
@testable import BooksBrowser

@Suite struct WCAGContrastTests {

    /// 將 SwiftUI `Color` 轉成 sRGB 0-1 三元組（透過 UIColor cross-bridge，
    /// 跳過 alpha / wide-gamut，足以驗證 palette tokens 的 luminance）。
    private func srgb(_ color: Color) -> (r: Double, g: Double, b: Double) {
        #if canImport(UIKit)
        let ui = UIColor(color)
        var r: CGFloat = 0, g: CGFloat = 0, b: CGFloat = 0, a: CGFloat = 0
        ui.getRed(&r, green: &g, blue: &b, alpha: &a)
        return (Double(r), Double(g), Double(b))
        #else
        return (0, 0, 0)
        #endif
    }

    /// WCAG 2.x relative luminance（sRGB → linear → weighted sum）。
    private func luminance(_ color: Color) -> Double {
        let (r, g, b) = srgb(color)
        func channel(_ v: Double) -> Double {
            v <= 0.03928 ? v / 12.92 : pow((v + 0.055) / 1.055, 2.4)
        }
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)
    }

    /// (L_lighter + 0.05) / (L_darker + 0.05)
    private func contrast(_ fg: Color, _ bg: Color) -> Double {
        let l1 = luminance(fg)
        let l2 = luminance(bg)
        let (hi, lo) = l1 > l2 ? (l1, l2) : (l2, l1)
        return (hi + 0.05) / (lo + 0.05)
    }

    // MARK: - Light theme guarantees

    @Test func accentLight_meetsAA_onCard() {
        // accentLight 作為連結文字色，貼在白色卡片上需 ≥4.5:1。
        #expect(contrast(AppColors.accentLight, AppTheme.light.palette.cardBackground) >= 4.5)
    }

    @Test func brandHeroLight_meetsAA_forWhiteText() {
        // brandHeroLight 是主 CTA 背景，白字疊上需 ≥4.5:1。
        #expect(contrast(AppColors.onBrandHero, AppColors.brandHeroLight) >= 4.5)
    }

    @Test func primaryText_light_meetsAAA() {
        // 正文（暖近黑 #37352F）需 ≥7:1 達 AAA。
        #expect(contrast(AppTheme.light.palette.primaryText, AppTheme.light.palette.cardBackground) >= 7.0)
    }

    @Test func destructiveLight_meetsAA() {
        #expect(contrast(AppColors.destructiveLight, AppTheme.light.palette.cardBackground) >= 4.5)
    }

    @Test func savedLight_meetsAA() {
        #expect(contrast(AppColors.savedLight, AppTheme.light.palette.cardBackground) >= 4.5)
    }

    // MARK: - Dark theme guarantees

    @Test func accentDark_meetsAA_onPage() {
        // accentDark 連結色貼於深灰頁面（#191919）需 ≥4.5:1。
        #expect(contrast(AppColors.accentDark, AppTheme.dark.palette.pageBackground) >= 4.5)
    }

    @Test func brandHeroDark_meetsAA_forWhiteText() {
        // brandHeroDark 是 dark mode CTA bg，白字 ≥4.5:1。
        #expect(contrast(AppColors.onBrandHero, AppColors.brandHeroDark) >= 4.5)
    }

    @Test func primaryText_dark_meetsAAA() {
        #expect(contrast(AppTheme.dark.palette.primaryText, AppTheme.dark.palette.pageBackground) >= 7.0)
    }

    @Test func destructiveDark_meetsAA() {
        #expect(contrast(AppColors.destructiveDark, AppTheme.dark.palette.pageBackground) >= 4.5)
    }

    @Test func savedDark_meetsAA() {
        #expect(contrast(AppColors.savedDark, AppTheme.dark.palette.pageBackground) >= 4.5)
    }

    // MARK: - Metadata tier (≥3:1, graphical / large text)

    @Test func secondaryText_light_meetsAALarge() {
        #expect(contrast(AppTheme.light.palette.secondaryText, AppTheme.light.palette.cardBackground) >= 4.5)
    }

    @Test func tertiaryText_light_meetsGraphical() {
        #expect(contrast(AppTheme.light.palette.tertiaryText, AppTheme.light.palette.cardBackground) >= 3.0)
    }

    @Test func secondaryText_dark_meetsAALarge() {
        #expect(contrast(AppTheme.dark.palette.secondaryText, AppTheme.dark.palette.pageBackground) >= 4.5)
    }

    @Test func tertiaryText_dark_meetsGraphical() {
        #expect(contrast(AppTheme.dark.palette.tertiaryText, AppTheme.dark.palette.pageBackground) >= 3.0)
    }
}
