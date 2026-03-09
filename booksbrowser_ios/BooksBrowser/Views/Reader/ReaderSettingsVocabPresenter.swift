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
                    .frame(
                        width: vocabSkin.metrics.readerSettingsHandleWidth,
                        height: vocabSkin.metrics.readerSettingsHandleHeight
                    )
                    .padding(.top, vocabSkin.metrics.readerSettingsHandleTopInset)
                    .padding(.bottom, vocabSkin.metrics.readerSettingsHandleBottomInset)

                headerBlock

                ScrollView {
                    VStack(alignment: .leading, spacing: vocabSkin.metrics.readerSettingsSectionSpacing) {
                        typographySection
                        appearanceSection
                        highlightSection
                        modeSection
                        debugSection
                    }
                    .padding(.horizontal, vocabSkin.metrics.readerSettingsHorizontalInset)
                    .padding(.bottom, vocabSkin.metrics.readerSettingsBottomInset)
                }
            }
        }
        .shadow(
            color: vocabSkin.palette.shadow.opacity(vocabSkin.metrics.readerPanelShadowOpacity),
            radius: vocabSkin.metrics.readerPanelShadowRadius,
            y: vocabSkin.metrics.readerPanelShadowY
        )
    }

    private var headerBlock: some View {
        HStack(alignment: .top, spacing: vocabSkin.metrics.readerSettingsHeaderSpacing) {
            VStack(alignment: .leading, spacing: 6) {
                Text("reader")
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .tracking(1.2)

                Text("閱讀設定")
                    .font(vocabSkin.typography.sectionTitle)
                    .foregroundStyle(vocabSkin.palette.primaryText)
            }

            Spacer()

            VocabChromeIconButton(systemImage: "xmark", action: onDismiss)
        }
        .padding(.horizontal, vocabSkin.metrics.readerSettingsHorizontalInset)
        .padding(.bottom, vocabSkin.metrics.readerSettingsHeaderBottomInset)
    }

    private var typographySection: some View {
        settingsSection(
            title: "排版",
            eyebrow: "Typography"
        ) {
            VStack(alignment: .leading, spacing: 16) {
                HStack(alignment: .center, spacing: 14) {
                    typographyAdjustButton(
                        title: "A",
                        size: 15,
                        enabled: state.canDecreaseFontSize,
                        action: onDecreaseFontSize
                    )

                    VStack(spacing: 4) {
                        Text(state.fontSizeText)
                            .font(.system(size: 28, weight: .semibold, design: .monospaced))
                            .foregroundStyle(vocabSkin.palette.primaryText)
                        Text("字級倍率")
                            .font(vocabSkin.typography.caption)
                            .foregroundStyle(vocabSkin.palette.tertiaryText)
                    }
                    .frame(maxWidth: .infinity)

                    typographyAdjustButton(
                        title: "A",
                        size: 28,
                        enabled: state.canIncreaseFontSize,
                        action: onIncreaseFontSize
                    )
                }

                Divider()
                    .overlay(vocabSkin.palette.divider)

                HStack(alignment: .center, spacing: 12) {
                    labelChip(title: "行距", systemImage: "text.line.spacing")

                    Slider(value: bindings.lineHeight, in: 1.0...2.5, step: 0.1)
                        .tint(vocabSkin.palette.primaryText)

                    Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                        .font(vocabSkin.typography.monoBodyStrong)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                        .frame(width: 34, alignment: .trailing)
                }
            }
        }
    }

    private var appearanceSection: some View {
        settingsSection(
            title: "外觀",
            eyebrow: "Atmosphere"
        ) {
            VStack(alignment: .leading, spacing: 16) {
                Menu {
                    ForEach(ReaderFont.allCases) { font in
                        Button(font.rawValue) {
                            bindings.font.wrappedValue = font
                        }
                    }
                } label: {
                    HStack(spacing: 12) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text("字體")
                                .font(vocabSkin.typography.captionStrong)
                                .foregroundStyle(vocabSkin.palette.tertiaryText)
                            Text(bindings.font.wrappedValue.rawValue)
                                .font(vocabSkin.typography.translationTitle)
                                .foregroundStyle(vocabSkin.palette.primaryText)
                        }

                        Spacer()

                        HStack(spacing: 6) {
                            Text(fontToneLabel)
                                .font(vocabSkin.typography.monoLabel)
                                .foregroundStyle(vocabSkin.palette.quaternaryText)
                            Image(systemName: "chevron.down")
                                .font(vocabSkin.typography.iconTiny.weight(.bold))
                                .foregroundStyle(vocabSkin.palette.tertiaryText)
                        }
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 14)
                    .background(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                            .fill(vocabSkin.palette.pageBackground)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                            .stroke(vocabSkin.palette.cardBorder, lineWidth: 1)
                    )
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)

                HStack(spacing: 10) {
                    ForEach(ReaderTheme.allCases) { theme in
                        themeTile(theme)
                    }
                }
            }
        }
    }

    private var highlightSection: some View {
        settingsSection(
            title: "生字標記",
            eyebrow: "Highlights"
        ) {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("底線強度")
                        .font(vocabSkin.typography.captionStrong)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)

                    Spacer()

                    Text(highlightIntensityLabel)
                        .font(vocabSkin.typography.monoLabel)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                HStack(spacing: 8) {
                    ForEach(opacityOptions, id: \.label) { option in
                        highlightOptionTile(option)
                    }
                }
            }
        }
    }

    private var modeSection: some View {
        settingsSection(
            title: "閱讀介面",
            eyebrow: "Render Mode"
        ) {
            HStack(spacing: 10) {
                ForEach(TranslationPanelMode.allCases) { mode in
                    modeTile(mode)
                }
            }
        }
    }

    private var debugSection: some View {
        settingsSection(
            title: "開發者與除錯",
            eyebrow: "Debug"
        ) {
            HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("顯示點擊熱區")
                        .font(vocabSkin.typography.body.weight(.medium))
                        .foregroundStyle(vocabSkin.palette.primaryText)
                    Text("用於校正 reader hit-testing。")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(vocabSkin.palette.tertiaryText)
                }

                Spacer()

                Toggle("", isOn: bindings.showHitTestingDebug)
                    .labelsHidden()
                    .tint(vocabSkin.palette.primaryText)
            }
        }
    }

    private func settingsSection<Content: View>(
        title: String,
        eyebrow: String,
        @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(eyebrow)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .tracking(1.0)
                Text(title)
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }
            .padding(.horizontal, 4)

            AppSectionCard(padding: 16, style: .settings(vocabSkin)) {
                content()
            }
        }
    }

    private func typographyAdjustButton(title: String, size: CGFloat, enabled: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            VStack(spacing: 6) {
                Text(title)
                    .font(.system(size: size, weight: .medium))
                Text(enabled ? "調整" : "上限")
                    .font(vocabSkin.typography.monoLabel)
                    .opacity(enabled ? 0.72 : 0.5)
            }
            .foregroundStyle(enabled ? vocabSkin.palette.primaryText : vocabSkin.palette.quaternaryText)
            .frame(width: 86, height: 82)
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

    private func labelChip(title: String, systemImage: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconTiny)
            Text(title)
                .font(vocabSkin.typography.captionStrong)
        }
        .foregroundStyle(vocabSkin.palette.secondaryText)
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .background(
            Capsule(style: .continuous)
                .fill(vocabSkin.palette.mutedFill)
        )
    }

    private func themeTile(_ theme: ReaderTheme) -> some View {
        let isSelected = bindings.theme.wrappedValue == theme
        return Button {
            onSelectTheme(theme)
        } label: {
            VStack(alignment: .leading, spacing: 12) {
                Image(systemName: theme.icon)
                    .font(vocabSkin.typography.iconToolbar)
                Text(theme.rawValue)
                    .font(vocabSkin.typography.body.weight(isSelected ? .semibold : .regular))
                Rectangle()
                    .fill(themeSwatchColor(theme))
                    .frame(height: 8)
                    .clipShape(Capsule(style: .continuous))
            }
            .frame(maxWidth: .infinity)
            .padding(.horizontal, 14)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(isSelected ? vocabSkin.palette.mutedFill : vocabSkin.palette.pageBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(
                        isSelected ? vocabSkin.palette.cardBorder : vocabSkin.palette.divider.opacity(0.6),
                        lineWidth: 1
                    )
            )
            .foregroundStyle(
                isSelected
                    ? vocabSkin.palette.primaryText
                    : vocabSkin.palette.secondaryText
            )
        }
        .buttonStyle(.plain)
    }

    private func highlightOptionTile(_ option: (label: String, value: Double)) -> some View {
        let isSelected = bindings.underlineOpacity.wrappedValue == option.value
        return Button {
            onSelectUnderlineOpacity(option.value)
        } label: {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text(option.label.localized)
                        .font(vocabSkin.typography.captionStrong)
                    Spacer()
                    if isSelected {
                        Image(systemName: "checkmark")
                            .font(vocabSkin.typography.iconTiny.weight(.bold))
                    }
                }

                Rectangle()
                    .fill(highlightPreviewColor(for: option.value))
                    .frame(height: option.value == 0 ? 1 : max(2, option.value * 6))
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .clipShape(Capsule(style: .continuous))
                    .padding(.trailing, 22)
            }
            .frame(maxWidth: .infinity, minHeight: 78, alignment: .topLeading)
            .padding(.horizontal, 12)
            .padding(.vertical, 12)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(isSelected ? vocabSkin.palette.mutedFill : vocabSkin.palette.pageBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(isSelected ? vocabSkin.palette.cardBorder : vocabSkin.palette.divider.opacity(0.6), lineWidth: 1)
            )
            .foregroundStyle(isSelected ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
        }
        .buttonStyle(.plain)
    }

    private func modeTile(_ mode: TranslationPanelMode) -> some View {
        let isSelected = bindings.translationPanelMode.wrappedValue == mode
        let icon = mode == .glass ? "sparkles.rectangle.stack" : "character.book.closed"
        return Button {
            bindings.translationPanelMode.wrappedValue = mode
        } label: {
            VStack(alignment: .leading, spacing: 8) {
                Image(systemName: icon)
                    .font(vocabSkin.typography.iconToolbar)
                Text(mode.label)
                    .font(vocabSkin.typography.translationTitle)
                Text(modeDescription(mode))
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(isSelected ? vocabSkin.palette.secondaryText : vocabSkin.palette.tertiaryText)
                    .multilineTextAlignment(.leading)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: .infinity, minHeight: 112, alignment: .topLeading)
            .padding(.horizontal, 14)
            .padding(.vertical, 14)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(isSelected ? vocabSkin.palette.mutedFill : vocabSkin.palette.pageBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .stroke(isSelected ? vocabSkin.palette.cardBorder : vocabSkin.palette.divider.opacity(0.6), lineWidth: 1)
            )
            .foregroundStyle(isSelected ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
        }
        .buttonStyle(.plain)
    }

    private var fontToneLabel: String {
        switch bindings.font.wrappedValue {
        case .serif:
            return "classic"
        case .athelas:
            return "reader"
        case .sans:
            return "clean"
        case .mono:
            return "coded"
        }
    }

    private var highlightIntensityLabel: String {
        let value = bindings.underlineOpacity.wrappedValue
        switch value {
        case 0:
            return "hidden"
        case ..<0.2:
            return "soft"
        case ..<0.5:
            return "balanced"
        default:
            return "strong"
        }
    }

    private func themeSwatchColor(_ theme: ReaderTheme) -> Color {
        vocabSkin.readerThemeSwatchColor(theme)
    }

    private func highlightPreviewColor(for value: Double) -> Color {
        if value == 0 {
            return vocabSkin.palette.divider
        }
        return vocabSkin.palette.accent.opacity(0.35 + value * 0.65)
    }

    private func modeDescription(_ mode: TranslationPanelMode) -> String {
        switch mode {
        case .glass:
            return "保留中性、透明、較輕的 reader chrome。"
        case .vocab:
            return "使用詞庫語言，讓 panel 與內文標記更一致。"
        }
    }
}
