//
//  AppSurface.swift
//  BooksBrowser
//
//  共用的卡片、標籤與按鈕樣式。
//  設計語言：極簡知識美學 - 純白紙張 + 微投影 + Ghost 按鈕
//

import SwiftUI

// MARK: - AppCard (Pure White Paper)

struct AppCard<Content: View>: View {
    @Environment(\.appTheme) private var appTheme
    let padding: CGFloat
    @ViewBuilder var content: Content

    init(
        padding: CGFloat = AppMetrics.spacingLarge,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding
        self.content = content()
    }

    var body: some View {
        content
            .padding(padding)
            .background(cardBackground)
            .clipShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous))
            .overlay(cardBorder.allowsHitTesting(false))
            .shadow(
                color: .black.opacity(AppShadows.paperFloatOpacity),
                radius: AppShadows.paperFloatRadius,
                y: AppShadows.paperFloatY
            )
    }

    private var cardBackground: some View {
        RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
            .fill(appTheme.palette.elevatedCardBackground)
    }

    private var cardBorder: some View {
        RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
            .strokeBorder(appTheme.palette.cardBorder, lineWidth: 0.5)
    }
}

// MARK: - AppTag (Minimalist)

struct AppTag: View {
    @Environment(\.colorScheme) private var colorScheme
    let text: String
    let tone: Color

    var body: some View {
        Text(text.localized)
            .font(AppFonts.caption(weight: .semibold))
            .padding(.horizontal, AppTagMetrics.horizontalPadding)
            .padding(.vertical, AppTagMetrics.verticalPadding)
            .background(tone.opacity(colorScheme == .dark ? 0.18 : 0.08))
            .foregroundStyle(tone)
            .clipShape(Capsule())
    }
}

// MARK: - GhostButtonStyle

/// 幽靈按鈕 — 無背景、低對比，按下時微微顯現
struct GhostButtonStyle: ButtonStyle {
    let tone: Color

    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .foregroundStyle(tone)
            .padding(.horizontal, AppGhostButtonMetrics.horizontalPadding)
            .padding(.vertical, AppGhostButtonMetrics.verticalPadding)
            .background(
                Capsule()
                    .fill(tone.opacity(configuration.isPressed ? 0.08 : 0))
            )
            .opacity(configuration.isPressed ? 0.7 : 1.0)
            .animation(AppMotion.quickEaseOut, value: configuration.isPressed)
    }
}

extension ButtonStyle where Self == GhostButtonStyle {
    static func ghost(_ tone: Color) -> GhostButtonStyle {
        GhostButtonStyle(tone: tone)
    }
}

// MARK: - compatibleGlass (toolbar-only)

extension View {
    @ViewBuilder
    func compatibleGlass(
        in shape: some Shape = Capsule(),
        interactive: Bool = false
    ) -> some View {
        if #available(iOS 26.0, *) {
            let g: Glass = interactive ? .regular.interactive() : .regular
            self.glassEffect(g, in: shape)
        } else {
            self.background(
                shape.fill(.ultraThinMaterial)
                    .overlay(shape.stroke(Color.primary.opacity(AppMetrics.glassStrokeOpacity), lineWidth: 1))
            )
        }
    }
}
