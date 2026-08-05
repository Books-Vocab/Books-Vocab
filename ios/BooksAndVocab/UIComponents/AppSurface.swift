//
//  AppSurface.swift
//  Books & Vocab
//
//  共用的卡片、標籤與按鈕樣式。
//  設計語言：極簡知識美學 - 純白紙張 + 微投影 + Ghost 按鈕
//

import SwiftUI

/// Ghost 按鈕內距 — 僅 AppSurface 使用。
private enum AppGhostButtonMetrics {
    static let horizontalPadding: CGFloat = 14
    static let verticalPadding: CGFloat = 10
}

// MARK: - AppCard (Pure White Paper)

/// AppCard surface variant.
///
/// 預設 `.elevated`（既有行為：cardBorder + z2 shadow）。
/// Mochi 化北極星二（border 退場）後新元件預設應用 `.flat` — 無 border、無 shadow，
/// 純 background 區隔。`elevated` 保留給 modal / popover / sticky group 等必須有邊界的場景。
enum AppCardVariant {
    /// 既有：border + z2 shadow（modal / popover / sticky group）。
    case elevated
    /// Mochi 化預設：純 background、無 border、無 shadow。
    case flat
    /// 完全透明：連 background 都不上，僅佔 layout（坐在 page bg 上的群組容器）。
    case ghost
}

struct AppCard<Content: View>: View {
    @Environment(\.appTheme) private var appTheme
    let padding: CGFloat
    let variant: AppCardVariant
    @ViewBuilder var content: Content

    init(
        padding: CGFloat = AppSpacing.s6,
        variant: AppCardVariant = .elevated,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding
        self.variant = variant
        self.content = content()
    }

    var body: some View {
        let shape = AppRoundedRect(roundness: AppRoundness.card)
        switch variant {
        case .elevated:
            content
                .padding(padding)
                .background(shape.fill(appTheme.palette.elevatedCardBackground))
                .clipShape(shape)
                .overlay(
                    shape
                        .strokeBorder(appTheme.palette.cardBorder, lineWidth: 0.5)
                        .allowsHitTesting(false)
                )
                .appElevation(.z2)
        case .flat:
            content
                .padding(padding)
                .background(shape.fill(appTheme.palette.cardBackground))
                .clipShape(shape)
                .appElevation(.z0)
        case .ghost:
            content
                .padding(padding)
                // 無 background、無 shadow — 完全透到 page bg
                .appElevation(.z0)
        }
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
            .clipShape(AppRoundedRect(roundness: AppRoundness.pill))
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
                AppRoundedRect(roundness: AppRoundness.pill)
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

#Preview("AppCard variants") {
    AppThemeContainer {
        AppCardPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct AppCardPreview: View {
    @Environment(\.appTheme) private var appTheme

    var body: some View {
        VStack(spacing: AppSpacing.s4) {
            AppCard(variant: .elevated) {
                row("elevated", systemImage: "square.stack.3d.up")
            }
            AppCard(variant: .flat) {
                row("flat", systemImage: "rectangle")
            }
            AppCard(variant: .ghost) {
                row("ghost", systemImage: "rectangle.dashed")
            }
        }
        .padding()
        .background(appTheme.palette.pageBackground.ignoresSafeArea())
    }

    private func row(_ label: String, systemImage: String) -> some View {
        HStack(spacing: AppSpacing.s3) {
            Image(systemName: systemImage)
                .foregroundStyle(appTheme.palette.accent)
            Text(label)
                .font(AppFonts.body())
                .foregroundStyle(appTheme.palette.primaryText)
            Spacer()
            AppTag(text: label, tone: appTheme.palette.accent)
        }
    }
}
