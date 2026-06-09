//
//  WCAGContrastTests.swift
//  Books & Vocab Tests
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

    // MARK: - Palette contrast guarantees (light / dark / metadata tiers)

    @Test(arguments: [
        // accentLight 作為連結文字色，貼在白色卡片上需 ≥4.5:1。
        (AppColors.accentLight, AppTheme.light.palette.cardBackground, 4.5),
        // 奶黃 brandHeroLight + onBrandHero (deep charcoal) ≥ 4.5:1。
        // 不再支援 .white 作為前景（奶黃 + 白字 fail AA）。
        (AppColors.onBrandHero, AppColors.brandHeroLight, 4.5),
        // 正文（暖近黑 #37352F）需 ≥7:1 達 AAA。
        (AppTheme.light.palette.primaryText, AppTheme.light.palette.cardBackground, 7.0),
        (AppColors.destructiveLight, AppTheme.light.palette.cardBackground, 4.5),
        (AppColors.savedLight, AppTheme.light.palette.cardBackground, 4.5),
        // accentDark 連結色貼於深灰頁面（#191919）需 ≥4.5:1。
        (AppColors.accentDark, AppTheme.dark.palette.pageBackground, 4.5),
        // 奶黃 brandHeroDark + onBrandHero (deep charcoal) ≥ 4.5:1（實測 ~7.05:1）。
        (AppColors.onBrandHero, AppColors.brandHeroDark, 4.5),
        (AppTheme.dark.palette.primaryText, AppTheme.dark.palette.pageBackground, 7.0),
        (AppColors.destructiveDark, AppTheme.dark.palette.pageBackground, 4.5),
        (AppColors.savedDark, AppTheme.dark.palette.pageBackground, 4.5),
        // Metadata tier (≥3:1, graphical / large text)
        (AppTheme.light.palette.secondaryText, AppTheme.light.palette.cardBackground, 4.5),
        (AppTheme.light.palette.tertiaryText, AppTheme.light.palette.cardBackground, 3.0),
        (AppTheme.dark.palette.secondaryText, AppTheme.dark.palette.pageBackground, 4.5),
        (AppTheme.dark.palette.tertiaryText, AppTheme.dark.palette.pageBackground, 3.0),
    ])
    func meetsContrast(fg: Color, bg: Color, min: Double) {
        #expect(contrast(fg, bg) >= min)
    }

    // MARK: - appAction(.primary) button label legibility
    //
    // Regression guard for the dark-mode invisibility bug: the primary tone used
    // a hardcoded `.white` foreground on the `primaryText` fill. In dark mode
    // primaryText = #E6E6E3 (near white), so white-on-near-white ≈ 1.05:1 —
    // effectively invisible. These assert the REAL pairing the style returns
    // (via AppActionButtonStyle.palette) flips with the scheme and stays legible.

    @Test(arguments: [AppTheme.light, AppTheme.dark, AppTheme.sepia])
    func primaryButtonLabelMeetsAA(theme: AppTheme) {
        let p = AppActionButtonStyle.palette(tone: .primary, theme: theme)
        #expect(contrast(p.foreground, p.background) >= 4.5)
    }
}
