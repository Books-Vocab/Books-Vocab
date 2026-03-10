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

enum AppTagMetrics {
    static let horizontalPadding: CGFloat = 10
    static let verticalPadding: CGFloat = 5
}

enum AppGhostButtonMetrics {
    static let horizontalPadding: CGFloat = 14
    static let verticalPadding: CGFloat = 10
}

enum AppBannerMetrics {
    static let spacing: CGFloat = 10
    static let horizontalPadding: CGFloat = 14
    static let verticalPadding: CGFloat = 8
    static let borderOpacity: Double = 0.2
    static let backgroundOpacity: Double = 0.08
}

enum AppMotion {
    static let quickEaseOut = Animation.easeOut(duration: 0.15)
    static let controlEaseOut = Animation.easeOut(duration: 0.14)
    static let chipSelectionEaseOut = Animation.easeOut(duration: 0.18)
    static let progressLinear = Animation.linear(duration: 0.1)
    static let standardSpring = Animation.spring(response: 0.3, dampingFraction: 0.75)
    static let emphasizedSpring = Animation.spring(response: 0.35, dampingFraction: 0.8)
    static let relaxedSpring = Animation.spring(response: 0.4, dampingFraction: 0.8)
    static let systemSpring = Animation.spring()
    static let modalSwapSpring = Animation.spring(response: 0.45, dampingFraction: 0.85)
    static let buttonSpring = Animation.spring(response: 0.35, dampingFraction: 0.7, blendDuration: 0)
    static let breathing = Animation.easeInOut(duration: 2.8).repeatForever(autoreverses: true)
    static let reviewRevealSpring = Animation.spring(response: 0.42, dampingFraction: 0.88)
    static let reviewNavigationSpring = Animation.spring(response: 0.32, dampingFraction: 0.86)
    static let reviewCardSwapSpring = Animation.spring(response: 0.34, dampingFraction: 0.84)

    // Swipe gesture
    static let swipeDismissSpring = Animation.spring(response: 0.35, dampingFraction: 0.78)
    static let swipeSnapBackSpring = Animation.spring(response: 0.4, dampingFraction: 0.82)

    // Semantic motion tokens for shared interaction patterns.
    static let panelState = standardSpring
    static let panelSnapBack = standardSpring
    static let headerState = relaxedSpring
    static let phaseChange = emphasizedSpring
    static let feedbackPulse = systemSpring
    static let contentFade = quickEaseOut
    static let loadingState = quickEaseOut
}

extension AnyTransition {
    static let overlayFade = AnyTransition.opacity
    static let readerPanelReveal = AnyTransition.move(edge: .bottom).combined(with: .opacity)
    static let headerSwap = AnyTransition.scale(scale: 0.8, anchor: .topTrailing).combined(with: .opacity)
    static let feedbackBadge = AnyTransition.scale(scale: 0.8).combined(with: .opacity)
    static let linkedOverlayCard = AnyTransition.scale(scale: 0.96).combined(with: .opacity)
    static let modalSwap = AnyTransition.asymmetric(
        insertion: .scale(scale: 0.97).combined(with: .opacity),
        removal: .opacity
    )
    static let statusRowReveal = AnyTransition.move(edge: .top).combined(with: .opacity)
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
