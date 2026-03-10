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
            .animation(AppMotion.controlEaseOut, value: configuration.isPressed)
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
        case .outline:
            return (
                appTheme.palette.primaryText,
                .clear,
                appTheme.palette.secondaryText.opacity(0.3)
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

#Preview("AppActionButtonStyle") {
    AppThemeContainer {
        AppActionButtonPreview()
    }
}

private struct AppActionButtonPreview: View {
    var body: some View {
        VStack(spacing: 12) {
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
