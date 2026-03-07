//
//  AppSurface.swift
//  BooksBrowser
//
//  共用的卡片與語義標籤樣式，避免各頁自行拼裝視覺語法。
//  iOS 26+：採用 Liquid Glass；舊版保持 Morandi 紙張質感 fallback。
//

import SwiftUI

// MARK: - compatibleGlass Helper

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
                    .overlay(
                        LinearGradient(
                            colors: [.white.opacity(0.3), .clear],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .overlay(shape.stroke(.white.opacity(0.2), lineWidth: 1))
            )
        }
    }

    @ViewBuilder
    func compatibleGlassCard() -> some View {
        if #available(iOS 26.0, *) {
            self.glassEffect(
                .regular,
                in: RoundedRectangle(
                    cornerRadius: AppMetrics.cornerRadiusExtraLarge,
                    style: .continuous
                )
            )
        } else {
            self
                .background(cardFallbackBackground)
                .overlay(cardFallbackBorder)
                .clipShape(
                    RoundedRectangle(
                        cornerRadius: AppMetrics.cornerRadiusExtraLarge,
                        style: .continuous
                    )
                )
        }
    }

    // Fallback helpers (pre-iOS 26)
    private var cardFallbackBackground: some View {
        RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
            .fill(.ultraThinMaterial)
            .overlay(
                RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
                    .fill(Color.white.opacity(0.7))
            )
    }

    private var cardFallbackBorder: some View {
        RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
            .strokeBorder(Color.primary.opacity(0.06), lineWidth: 0.8)
    }
}

// MARK: - AppCard

struct AppCard<Content: View>: View {
    @Environment(\.colorScheme) private var colorScheme
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
            .compatibleGlassCard()
    }
}

// MARK: - AppTag

struct AppTag: View {
    @Environment(\.colorScheme) private var colorScheme
    let text: String
    let tone: Color

    var body: some View {
        if #available(iOS 26.0, *) {
            Text(text)
                .font(AppFonts.caption(weight: .semibold))
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .foregroundStyle(tone)
                .glassEffect(.regular.tint(tone), in: Capsule())
        } else {
            Text(text)
                .font(AppFonts.caption(weight: .semibold))
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(tone.opacity(colorScheme == .dark ? 0.20 : 0.10))
                .foregroundStyle(tone)
                .clipShape(Capsule())
        }
    }
}
