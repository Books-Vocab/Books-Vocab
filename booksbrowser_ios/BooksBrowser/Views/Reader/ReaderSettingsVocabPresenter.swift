import SwiftUI

struct ReaderSettingsVocabPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: ReaderSettingsPanelPresenter.State
    let bindings: ReaderSettingsPanelPresenter.Bindings
    let onDecreaseFontSize: () -> Void
    let onIncreaseFontSize: () -> Void
    let onSelectTheme: (ReaderTheme) -> Void
    let onSelectUnderlineOpacity: (Double) -> Void
    let onDismiss: () -> Void

    private let opacityOptions: [(label: String, value: Double)] = [
        ("隱藏", 0.0),
        ("淡", 0.15),
        ("中", 0.35),
        ("深", 0.60)
    ]

    var body: some View {
        VocabCard(padding: 0) {
            VStack(spacing: 0) {
                Capsule(style: .continuous)
                    .fill(vocabSkin.palette.quaternaryText.opacity(0.24))
                    .frame(width: 38, height: 4)
                    .padding(.top, 10)
                    .padding(.bottom, 8)

                VocabOverlayHeader(
                    title: "閱讀設定",
                    systemImage: "textformat.size",
                    onClose: onDismiss
                )

                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        settingsSection(title: "排版") {
                            VStack(spacing: 0) {
                                HStack(spacing: 12) {
                                    fontSizeButton(title: "A", size: 14, enabled: state.canDecreaseFontSize, action: onDecreaseFontSize)

                                    Text(state.fontSizeText)
                                        .font(vocabSkin.typography.monoBody)
                                        .foregroundStyle(vocabSkin.palette.secondaryText)
                                        .frame(width: 58)

                                    fontSizeButton(title: "A", size: 24, enabled: state.canIncreaseFontSize, action: onIncreaseFontSize)
                                }
                                .padding(.horizontal, 16)
                                .padding(.vertical, 14)

                                divider

                                HStack(spacing: 14) {
                                    Image(systemName: "text.line.spacing")
                                        .font(vocabSkin.typography.iconSmall)
                                        .foregroundStyle(vocabSkin.palette.secondaryText)

                                    Slider(value: bindings.lineHeight, in: 1.0...2.5, step: 0.1)
                                        .tint(vocabSkin.palette.primaryText)

                                    Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                                        .font(vocabSkin.typography.monoBody)
                                        .foregroundStyle(vocabSkin.palette.secondaryText)
                                        .frame(width: 32, alignment: .trailing)
                                }
                                .padding(.horizontal, 16)
                                .padding(.vertical, 14)
                            }
                        }

                        settingsSection(title: "外觀") {
                            VStack(spacing: 0) {
                                Menu {
                                    ForEach(ReaderFont.allCases) { font in
                                        Button(font.rawValue) {
                                            bindings.font.wrappedValue = font
                                        }
                                    }
                                } label: {
                                    HStack {
                                        Text("字體")
                                            .font(vocabSkin.typography.body)
                                            .foregroundStyle(vocabSkin.palette.primaryText)

                                        Spacer()

                                        HStack(spacing: 6) {
                                            Text(bindings.font.wrappedValue.rawValue)
                                                .font(vocabSkin.typography.body)
                                                .foregroundStyle(vocabSkin.palette.secondaryText)
                                            Image(systemName: "chevron.up.chevron.down")
                                                .font(vocabSkin.typography.iconTiny)
                                                .foregroundStyle(vocabSkin.palette.tertiaryText)
                                        }
                                    }
                                    .padding(.horizontal, 16)
                                    .padding(.vertical, 14)
                                    .contentShape(Rectangle())
                                }
                                .buttonStyle(.plain)

                                divider

                                HStack(spacing: 8) {
                                    ForEach(ReaderTheme.allCases) { theme in
                                        themeButton(theme)
                                    }
                                }
                                .padding(.horizontal, 12)
                                .padding(.vertical, 12)
                            }
                        }

                        settingsSection(title: "生字底線強度") {
                            HStack(spacing: 8) {
                                ForEach(opacityOptions, id: \.label) { option in
                                    selectionButton(
                                        title: option.label.localized,
                                        isSelected: bindings.underlineOpacity.wrappedValue == option.value
                                    ) {
                                        onSelectUnderlineOpacity(option.value)
                                    }
                                }
                            }
                            .padding(12)
                        }

                        settingsSection(title: "開發者與除錯") {
                            HStack {
                                Text("顯示點擊熱區")
                                    .font(vocabSkin.typography.body)
                                    .foregroundStyle(vocabSkin.palette.primaryText)

                                Spacer()

                                Toggle("", isOn: bindings.showHitTestingDebug)
                                    .labelsHidden()
                                    .tint(vocabSkin.palette.primaryText)
                            }
                            .padding(.horizontal, 16)
                            .padding(.vertical, 14)
                        }

                        settingsSection(title: "閱讀介面風格") {
                            HStack(spacing: 8) {
                                ForEach(TranslationPanelMode.allCases) { mode in
                                    selectionButton(
                                        title: mode.label,
                                        isSelected: bindings.translationPanelMode.wrappedValue == mode
                                    ) {
                                        bindings.translationPanelMode.wrappedValue = mode
                                    }
                                }
                            }
                            .padding(12)
                        }
                    }
                    .padding(.horizontal, 16)
                    .padding(.bottom, 16)
                }
            }
        }
        .shadow(color: vocabSkin.palette.shadow.opacity(0.72), radius: 10, y: -3)
    }

    private func settingsSection<Content: View>(
        title: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title)
                .font(vocabSkin.typography.captionStrong)
                .foregroundStyle(vocabSkin.palette.tertiaryText)
                .padding(.horizontal, 4)

            AppSectionCard(padding: 0, style: .settings(vocabSkin)) {
                content()
            }
        }
    }

    private var divider: some View {
        Rectangle()
            .fill(vocabSkin.palette.divider)
            .frame(height: 1)
            .padding(.horizontal, 16)
    }

    private func fontSizeButton(title: String, size: CGFloat, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(.system(size: size, weight: .medium))
                .foregroundStyle(enabled ? vocabSkin.palette.primaryText : vocabSkin.palette.quaternaryText)
                .frame(maxWidth: .infinity)
                .frame(height: 44)
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

    private func themeButton(_ theme: ReaderTheme) -> some View {
        Button {
            onSelectTheme(theme)
        } label: {
            HStack(spacing: 6) {
                Image(systemName: theme.icon)
                    .font(vocabSkin.typography.iconSmall)
                Text(theme.rawValue)
                    .font(vocabSkin.typography.body)
                    .fontWeight(bindings.theme.wrappedValue == theme ? .semibold : .regular)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(bindings.theme.wrappedValue == theme ? vocabSkin.palette.mutedFill : .clear)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(
                        bindings.theme.wrappedValue == theme
                            ? vocabSkin.palette.cardBorder
                            : .clear,
                        lineWidth: 1
                    )
            )
            .foregroundStyle(
                bindings.theme.wrappedValue == theme
                    ? vocabSkin.palette.primaryText
                    : vocabSkin.palette.secondaryText
            )
        }
        .buttonStyle(.plain)
    }

    private func selectionButton(title: String, isSelected: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(title)
                .font(vocabSkin.typography.body)
                .fontWeight(isSelected ? .semibold : .regular)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .fill(isSelected ? vocabSkin.palette.mutedFill : .clear)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                        .stroke(isSelected ? vocabSkin.palette.cardBorder : .clear, lineWidth: 1)
                )
                .foregroundStyle(isSelected ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
        }
        .buttonStyle(.plain)
    }
}
