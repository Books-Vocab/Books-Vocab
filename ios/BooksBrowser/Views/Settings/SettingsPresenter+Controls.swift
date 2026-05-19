import SwiftUI

// MARK: - Stepper Buttons, Card/Chrome/TextInput Modifiers, Input Fields

struct SettingsStepperIconButton: View {
    @Environment(\.appSkin) private var appSkin
    let systemImage: String
    let enabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(appSkin.typography.iconMedium.weight(.medium))
                .foregroundStyle(enabled ? appSkin.palette.primaryText : appSkin.palette.quaternaryText)
                .frame(width: AppMetrics.iconButtonSize, height: AppMetrics.iconButtonSize)
                .background(
                    RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous)
                        .fill(appSkin.palette.pageBackground)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous)
                        .stroke(appSkin.palette.cardBorder, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

struct SettingsCardModifier: ViewModifier {
    @Environment(\.appSkin) private var appSkin

    func body(content: Content) -> some View {
        AppSectionCard(padding: 0, style: .settings(appSkin)) {
            content
        }
    }
}

extension View {
    func settingsCard() -> some View {
        modifier(SettingsCardModifier())
    }

    func appSettingsButtonChrome() -> some View {
        modifier(SettingsButtonChromeModifier())
    }

    func appSettingsTextInputStyle(alignment: TextAlignment = .trailing) -> some View {
        modifier(SettingsTextInputModifier(alignment: alignment))
    }
}

struct SettingsButtonChromeModifier: ViewModifier {
    @Environment(\.appSkin) private var appSkin

    func body(content: Content) -> some View {
        content
            .padding(appSkin.spacing.cardPadding)
            .background(appSkin.palette.pageBackground)
            .clipShape(RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous)
                    .stroke(appSkin.palette.cardBorder, lineWidth: 1)
            )
    }
}

struct SettingsTextInputModifier: ViewModifier {
    @Environment(\.appSkin) private var appSkin
    let alignment: TextAlignment

    func body(content: Content) -> some View {
        content
            .font(appSkin.typography.monoLabel)
            .multilineTextAlignment(alignment)
            .platformTextInputConfig()
    }
}

struct SettingsLabeledInputField<Content: View>: View {
    @Environment(\.appSkin) private var appSkin
    let title: String
    let content: Content

    init(title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.microGap) {
            Text(title)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.tertiaryText)

            content
        }
        .padding(appSkin.spacing.cardPadding)
        .background(appSkin.palette.pageBackground)
        .clipShape(RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: appSkin.radii.control, style: .continuous)
                .stroke(appSkin.palette.cardBorder, lineWidth: 1)
        )
    }
}
