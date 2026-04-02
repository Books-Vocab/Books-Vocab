import SwiftUI

// MARK: - Stepper Buttons, Card/Chrome/TextInput Modifiers, Input Fields

struct SettingsStepperIconButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let systemImage: String
    let enabled: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconMedium.weight(.medium))
                .foregroundStyle(enabled ? vocabSkin.palette.primaryText : vocabSkin.palette.quaternaryText)
                .frame(width: AppMetrics.iconButtonSize, height: AppMetrics.iconButtonSize)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(vocabSkin.palette.pageBackground)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                )
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

struct SettingsCardModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        AppSectionCard(padding: 0, style: .settings(vocabSkin)) {
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
    @Environment(\.vocabSkin) private var vocabSkin

    func body(content: Content) -> some View {
        content
            .padding(vocabSkin.spacing.cardPadding)
            .background(vocabSkin.palette.pageBackground)
            .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
            )
    }
}

struct SettingsTextInputModifier: ViewModifier {
    @Environment(\.vocabSkin) private var vocabSkin
    let alignment: TextAlignment

    func body(content: Content) -> some View {
        content
            .font(vocabSkin.typography.monoLabel)
            .multilineTextAlignment(alignment)
            .platformTextInputConfig()
    }
}

struct SettingsLabeledInputField<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let content: Content

    init(title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.microGap) {
            Text(title)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.tertiaryText)

            content
        }
        .padding(vocabSkin.spacing.cardPadding)
        .background(vocabSkin.palette.pageBackground)
        .clipShape(RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
        )
    }
}
