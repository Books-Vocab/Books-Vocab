//
//  AppSurface.swift
//  BooksBrowser
//
//  共用的卡片與語義標籤樣式，避免各頁自行拼裝視覺語法。
//

import SwiftUI

struct AppCard<Content: View>: View {
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
            .overlay(cardBorder)
            .clipShape(RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous))
    }

    private var cardBackground: some View {
        RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
            .fill(Color.white.opacity(0.72))
    }

    private var cardBorder: some View {
        RoundedRectangle(cornerRadius: AppMetrics.cornerRadiusExtraLarge, style: .continuous)
            .strokeBorder(Color.primary.opacity(0.04), lineWidth: 0.6)
    }
}

struct AppTag: View {
    @Environment(\.colorScheme) private var colorScheme
    let text: String
    let tone: Color

    var body: some View {
        Text(text)
            .font(AppFonts.caption(weight: .semibold))
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(tone.opacity(colorScheme == .dark ? 0.20 : 0.10))
            .foregroundStyle(tone)
            .clipShape(Capsule())
    }
}
