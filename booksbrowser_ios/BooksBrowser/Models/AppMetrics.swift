//
//  AppMetrics.swift
//  BooksBrowser
//
//  統一的間距、圓角與陰影參數 (Design System Tokens)
//

import SwiftUI

enum AppMetrics {
    // ── Spacing (留白與呼吸感) ────────────────────────────────────────────────────
    static let spacingExtraSmall: CGFloat = 4
    static let spacingSmall: CGFloat = 8
    static let spacingMedium: CGFloat = 16
    static let spacingLarge: CGFloat = 24
    static let spacingExtraLarge: CGFloat = 32
    static let spacingXXL: CGFloat = 48
    
    // ── Corner Radius (圓角) ───────────────────────────────────────────────────
    static let cornerRadiusSmall: CGFloat = 8
    static let cornerRadiusMedium: CGFloat = 12
    static let cornerRadiusLarge: CGFloat = 16
    static let cornerRadiusExtraLarge: CGFloat = 24
    static let cornerRadiusGlass: CGFloat = 30

    // ── Card Dimensions ─────────────────────────────────────────────────────────
    static let cardMinHeight: CGFloat = 420
    static let heroCardPadding: CGFloat = 34
    static let sectionInset: CGFloat = 20
}

enum AppShadows {
    // ── iOS 26 Liquid Glass & Morandi Paper Shadows ───────────────────────────
    // 極低對比度的大範圍陰影，模擬實體紙張微微浮起的效果
    static let paperFloatOpacity: Double = 0.04
    static let paperFloatRadius: CGFloat = 20
    static let paperFloatY: CGFloat = 8
    
    // 輕微的按下或緊貼陰影
    static let paperPressedOpacity: Double = 0.02
    static let paperPressedRadius: CGFloat = 4
    static let paperPressedY: CGFloat = 2
}
