//
//  HoverHighlight.swift
//  Books & Vocab
//
//  指標 hover 回饋 — 卡片浮起 / row tint。
//  .onHover 在純觸控裝置無指標事件,自動 no-op;iPad 觸控板 + Mac Catalyst 共益,故不分流。
//

import SwiftUI

// MARK: - Card hover lift

private struct AppHoverLift: ViewModifier {
    var scale: CGFloat
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var isHovered = false

    func body(content: Content) -> some View {
        // Reduce Motion 仍關 scale 動畫(ui-design.md);hover 退回無 transform,觸控本就無 hover。
        let effectiveScale = reduceMotion ? 1.0 : scale
        content
            .scaleEffect(isHovered ? effectiveScale : 1.0)
            .animation(AppMotion.quickEaseOut, value: isHovered)
            .onHover { isHovered = $0 }
    }
}

extension View {
    /// 指標 hover 時卡片輕微浮起(scale)。卡片屬按鈕互動,scale 合 motion 契約。
    /// 觸控 iPhone 無 hover event → no-op。
    func appHoverLift(scale: CGFloat = 1.02) -> some View {
        modifier(AppHoverLift(scale: scale))
    }
}

// MARK: - List row hover tint

private struct AppHoverRowTint: ViewModifier {
    let cornerRadius: CGFloat
    @Environment(\.appTheme) private var theme
    @State private var isHovered = false

    func body(content: Content) -> some View {
        content
            .background(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .fill(theme.palette.primaryText.opacity(isHovered ? 0.05 : 0))
            )
            .animation(AppMotion.quickEaseOut, value: isHovered)
            .onHover { isHovered = $0 }
    }
}

extension View {
    /// list row 指標 hover 時 bg tint(只動 background,合 motion 契約「非按鈕互動禁 transform」)。
    /// 觸控 iPhone 無 hover event → no-op。
    func appHoverRowTint(cornerRadius: CGFloat = AppRadius.md) -> some View {
        modifier(AppHoverRowTint(cornerRadius: cornerRadius))
    }
}

// MARK: - Pointer effect (chrome 控制項的桌面指標層)

extension View {
    /// 電腦模式(Mac Catalyst)/ iPad 觸控板:指標 hover 於可點控制項時套 UIKit pointer
    /// effect —— 指標 morph 貼合元件形狀 + 系統 highlight,提示「這裡可互動」。這是
    /// Catalyst 慣用的指標層(非 pointing-hand;`.pointerStyle` 在 Catalyst 不可用)。
    /// 觸控 iPhone 無指標事件 → 系統自動 no-op,故不分流。
    ///
    /// 適用:chip / segment / pill / plain icon button 等 chrome 控制項。
    /// (卡片走 `appHoverLift`;扁平 list row 走 `appHoverRowTint`。)
    func appPointerHover(_ effect: HoverEffect = .highlight) -> some View {
        hoverEffect(effect)
    }
}
