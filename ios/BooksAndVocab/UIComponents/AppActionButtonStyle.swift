import SwiftUI

enum AppActionTone {
    case primary
    case neutral
    case outline
    case destructive
}

struct AppActionButtonStyle: ButtonStyle {
    @Environment(\.appTheme) private var appTheme
    let tone: AppActionTone

    func makeBody(configuration: Configuration) -> some View {
        let palette = Self.palette(tone: tone, theme: appTheme)

        configuration.label
            .font(AppFonts.subhead(weight: .semibold))
            .foregroundStyle(palette.foreground)
            .frame(maxWidth: .infinity)
            .padding(.horizontal, AppSpacing.s4)
            .padding(.vertical, AppSpacing.actionButtonVerticalPadding)
            .background(
                AppRoundedRect(roundness: AppRoundness.control)
                    .fill(palette.background)
            )
            .overlay(
                AppRoundedRect(roundness: AppRoundness.control)
                    .stroke(palette.border, lineWidth: 1)
            )
            .opacity(configuration.isPressed ? 0.82 : 1)
            .scaleEffect(configuration.isPressed ? 0.992 : 1)
            .animateControl(configuration.isPressed)
    }

    /// Resolved (foreground, background, border) for a tone against a theme.
    /// Static + theme-injected so WCAGContrastTests can assert the real pairing
    /// without standing up a SwiftUI environment.
    static func palette(
        tone: AppActionTone,
        theme: AppTheme
    ) -> (foreground: Color, background: Color, border: Color) {
        switch tone {
        case .primary:
            // Foreground = pageBackground so it inverts WITH the scheme: light
            // text on the dark primaryText fill in light mode, dark text on the
            // near-white fill in dark mode. A hardcoded `.white` was invisible in
            // dark mode (white on #E6E6E3 ≈ 1.05:1).
            return (theme.palette.pageBackground, theme.palette.primaryText, theme.palette.primaryText)
        case .neutral:
            return (
                theme.palette.primaryText,
                theme.palette.cardBackground,
                theme.palette.cardBorder
            )
        case .outline:
            return (
                theme.palette.primaryText,
                .clear,
                theme.palette.secondaryText.opacity(0.3)
            )
        case .destructive:
            return (
                theme.palette.destructive,
                theme.palette.destructive.opacity(0.10),
                theme.palette.destructive.opacity(0.22)
            )
        }
    }
}

extension ButtonStyle where Self == AppActionButtonStyle {
    static func appAction(_ tone: AppActionTone = .primary) -> AppActionButtonStyle {
        AppActionButtonStyle(tone: tone)
    }
}

#Preview("AppActionButtonStyle") {
    AppThemeContainer {
        AppActionButtonPreview()
    }
    .environmentObject(AppAppearanceStore.preview)
}

private struct AppActionButtonPreview: View {
    var body: some View {
        VStack(spacing: AppSpacing.s3) {
            Button("主要操作") {}
                .buttonStyle(.appAction(.primary))
            Button("次要操作") {}
                .buttonStyle(.appAction(.neutral))
            Button("外框操作") {}
                .buttonStyle(.appAction(.outline))
            Button("危險操作") {}
                .buttonStyle(.appAction(.destructive))
        }
        .padding()
    }
}
