//
//  AppSurface.swift
//  BooksBrowser
//
//  共用的卡片、標籤與按鈕樣式。
//  設計語言：Mochi 式極簡知識美學 — 純白紙張 + 微投影 + Ghost 按鈕
//

import SwiftUI

enum AppShellMetrics {
    static let pageHorizontalPadding = AppMetrics.sectionInset
    static let pageTopPadding: CGFloat = 12
    static let pageBottomPadding: CGFloat = 48
    static let sectionSpacing: CGFloat = 24
    static let cardCornerRadius = AppMetrics.cornerRadiusMedium
    static let cardShadowRadius: CGFloat = 6
    static let cardShadowY: CGFloat = 2
    static let cardPadding: CGFloat = 18
    static let toolbarBadgeHorizontalPadding: CGFloat = 5
    static let toolbarBadgeVerticalPadding: CGFloat = 2
}

enum AppActionTone {
    case primary
    case neutral
    case destructive
}

struct AppSectionCard<Content: View>: View {
    @Environment(\.appTheme) private var appTheme
    let padding: CGFloat
    @ViewBuilder let content: Content

    init(
        padding: CGFloat = AppShellMetrics.cardPadding,
        @ViewBuilder content: () -> Content
    ) {
        self.padding = padding
        self.content = content()
    }

    var body: some View {
        content
            .padding(padding)
            .background(appTheme.palette.cardBackground)
            .clipShape(
                RoundedRectangle(
                    cornerRadius: AppShellMetrics.cardCornerRadius,
                    style: .continuous
                )
            )
            .overlay(
                RoundedRectangle(
                    cornerRadius: AppShellMetrics.cardCornerRadius,
                    style: .continuous
                )
                .stroke(appTheme.palette.cardBorder.opacity(0.7), lineWidth: 1)
            )
            .shadow(
                color: appTheme.palette.shadow,
                radius: AppShellMetrics.cardShadowRadius,
                y: AppShellMetrics.cardShadowY
            )
    }
}

struct AppToolbarGlyph: View {
    @Environment(\.appTheme) private var appTheme
    let systemImage: String
    let badge: String?
    let tone: Color?

    init(systemImage: String, badge: String? = nil, tone: Color? = nil) {
        self.systemImage = systemImage
        self.badge = badge
        self.tone = tone
    }

    var body: some View {
        HStack(spacing: AppMetrics.spacingExtraSmall) {
            Image(systemName: systemImage)
                .font(AppFonts.caption(weight: .medium))
                .foregroundStyle(tone ?? appTheme.palette.secondaryText)

            if let badge {
                Text(badge)
                    .font(AppFonts.monoNumbers(size: 10))
                    .foregroundStyle(.white)
                    .padding(.horizontal, AppShellMetrics.toolbarBadgeHorizontalPadding)
                    .padding(.vertical, AppShellMetrics.toolbarBadgeVerticalPadding)
                    .background(
                        RoundedRectangle(
                            cornerRadius: AppMetrics.cornerRadiusSmall - 1,
                            style: .continuous
                        )
                        .fill(tone ?? appTheme.palette.destructive)
                    )
            }
        }
    }
}

struct AppSectionHeader: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String

    var body: some View {
        Label(title.localized, systemImage: systemImage)
            .font(AppFonts.caption(weight: .semibold))
            .foregroundStyle(appTheme.palette.secondaryText)
            .padding(.leading, AppMetrics.spacingExtraSmall)
    }
}

struct AppSectionFooter: View {
    @Environment(\.appTheme) private var appTheme
    let text: String

    var body: some View {
        Text(text.localized)
            .font(AppFonts.caption())
            .foregroundStyle(appTheme.palette.tertiaryText)
            .lineSpacing(3)
            .padding(.horizontal, AppMetrics.spacingExtraSmall)
    }
}

struct AppEmptyStateContent: View {
    @Environment(\.appTheme) private var appTheme
    let title: String
    let systemImage: String
    let description: String

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: systemImage)
                .font(AppFonts.hero(weight: .light))
                .foregroundStyle(appTheme.palette.tertiaryText)

            Text(title.localized)
                .font(AppFonts.h2(weight: .semibold))
                .foregroundStyle(appTheme.palette.primaryText)

            Text(description.localized)
                .font(AppFonts.body())
                .foregroundStyle(appTheme.palette.secondaryText)
                .multilineTextAlignment(.center)
        }
        .frame(maxWidth: .infinity)
    }
}

struct AppEmptyStateCard: View {
    let title: String
    let systemImage: String
    let description: String

    var body: some View {
        AppSectionCard {
            AppEmptyStateContent(
                title: title,
                systemImage: systemImage,
                description: description
            )
            .padding(.vertical, 12)
        }
    }
}

struct AppActionButtonStyle: ButtonStyle {
    @Environment(\.appTheme) private var appTheme
    let tone: AppActionTone

    func makeBody(configuration: Configuration) -> some View {
        let palette = stylePalette

        configuration.label
            .font(AppFonts.subhead(weight: .semibold))
            .foregroundStyle(palette.foreground)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 16)
            .padding(.vertical, 13)
            .background(
                RoundedRectangle(
                    cornerRadius: AppMetrics.cornerRadiusMedium,
                    style: .continuous
                )
                .fill(palette.background)
            )
            .overlay(
                RoundedRectangle(
                    cornerRadius: AppMetrics.cornerRadiusMedium,
                    style: .continuous
                )
                .stroke(palette.border, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.82 : 1)
            .scaleEffect(configuration.isPressed ? 0.992 : 1)
            .animation(.easeOut(duration: 0.14), value: configuration.isPressed)
    }

    private var stylePalette: (foreground: Color, background: Color, border: Color) {
        switch tone {
        case .primary:
            return (.white, appTheme.palette.primaryText, appTheme.palette.primaryText)
        case .neutral:
            return (
                appTheme.palette.primaryText,
                appTheme.palette.cardBackground,
                appTheme.palette.cardBorder
            )
        case .destructive:
            return (
                appTheme.palette.destructive,
                appTheme.palette.destructive.opacity(0.10),
                appTheme.palette.destructive.opacity(0.22)
            )
        }
    }
}

extension ButtonStyle where Self == AppActionButtonStyle {
    static func appAction(_ tone: AppActionTone = .primary) -> AppActionButtonStyle {
        AppActionButtonStyle(tone: tone)
    }
}

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
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
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
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .background(
                Capsule()
                    .fill(tone.opacity(configuration.isPressed ? 0.08 : 0))
            )
            .opacity(configuration.isPressed ? 0.7 : 1.0)
            .animation(.easeOut(duration: 0.15), value: configuration.isPressed)
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
                    .overlay(shape.stroke(Color.primary.opacity(0.12), lineWidth: 1))
            )
        }
    }
}
