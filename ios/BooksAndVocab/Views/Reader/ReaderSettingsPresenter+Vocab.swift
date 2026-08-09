#if os(iOS)
import SwiftUI

// MARK: - Native Settings Form

/// 閱讀設定 — 與「複習節奏」「複習卡版面」共用**同一套原生心智模型**
/// （APP-20260808-f0770b 收斂 + APP-20260808-240a94 原生化）：
///
///   容器  `NavigationStack` + `Form`（呈現層由 `ReaderView` 的 `.sheet` 提供
///          detents 與 drag indicator，不再自繪 panel 卡片與 handle）
///   分組  `Section` + `SettingsSectionHeader` / `SettingsSectionFooter`
///   選擇  `Picker` —— 行內單值用 `.menu`，選項本身值得一列（帶 icon / 色票）用 `.inline`
///   數值  `Stepper`（上下界＝傳 nil 的 increment/decrement closure）與 `Slider`
///   開關  `Toggle`
///
/// 具名承認的代價：自繪的 selection tile、label chip、control surface、群組
/// air divider 全部退場，換來系統列樣式；襯線標題與自訂間距節奏隨之消失，
/// 主題選項的色票縮成一列內的小色塊。這是「一致性優先」的直接後果，
/// **不要**在 Section 內重新自繪把 editorial 個性救回來。
extension ReaderSettingsPresenter {

    // MARK: Layout

    var vocabLayout: some View {
        NavigationStack {
            Form {
                vocabPreviewSection
                vocabTypographySection
                vocabAppearanceSection
                vocabHighlightSection
                vocabDebugSection
            }
            .navigationTitle(L10n.string("閱讀設定"))
            .inlineNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(L10n.string("完成"), action: onDismiss)
                        .accessibilityIdentifier("reader.settings.done")
                }
            }
            .accessibilityElement(children: .contain)
            .accessibilityIdentifier("reader.settingsPanel")
        }
    }

    // MARK: Preview

    /// 即時預覽擺在控制項**之前**，與複習卡版面編輯器同一個順序邏輯
    /// （預覽 → 控制項 → 說明 footer）：先讓人看到現在長什麼樣，再讓人動旋鈕。
    ///
    /// 每一格都直接讀 binding 的當前值，沒有 draft、沒有 snapshot ——
    /// 所以它必然與正下方那些控制項一致，不需要靠誰記得同步。
    var vocabPreviewSection: some View {
        Section {
            ReaderSettingsPreviewCard(
                font: bindings.font.wrappedValue,
                fontScale: state.fontScale,
                lineHeight: bindings.lineHeight.wrappedValue,
                theme: bindings.theme.wrappedValue,
                vocabHighlightPreferences: VocabHighlightPreferences(
                    colorPreset: bindings.vocabHighlightColorPreset.wrappedValue,
                    opacity: bindings.underlineOpacity.wrappedValue
                )
            )
        } header: {
            SettingsSectionHeader(
                title: L10n.string("reader.settings.section.preview"),
                icon: "text.alignleft"
            )
        }
    }

    // MARK: Typography

    var vocabTypographySection: some View {
        Section {
            Stepper(
                onIncrement: state.canIncreaseFontSize ? onIncreaseFontSize : nil,
                onDecrement: state.canDecreaseFontSize ? onDecreaseFontSize : nil
            ) {
                LabeledContent(L10n.string("字級")) {
                    Text(state.fontSizeText).monospacedDigit()
                }
            }

            VStack(alignment: .leading, spacing: AppSpacing.s1) {
                LabeledContent(L10n.string("行距")) {
                    Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                        .monospacedDigit()
                }
                Slider(value: bindings.lineHeight, in: 1.0...2.5, step: 0.1)
                    .accessibilityLabel(L10n.string("行距"))
            }

            Picker(selection: bindings.scrollMode) {
                Text(L10n.string("翻頁")).tag(false)
                Text(L10n.string("捲動")).tag(true)
            } label: {
                Text(L10n.string("閱讀模式"))
            }
            .pickerStyle(.menu)
        } header: {
            SettingsSectionHeader(title: L10n.string("排版"), icon: "textformat.size")
        }
    }

    // MARK: Appearance

    var vocabAppearanceSection: some View {
        Section {
            Picker(selection: bindings.font) {
                ForEach(ReaderFont.allCases) { font in
                    Text(font.displayName).tag(font)
                }
            } label: {
                Text(L10n.string("字體"))
            }
            .pickerStyle(.menu)

            Picker(selection: themeSelection) {
                ForEach(ReaderTheme.allCases) { theme in
                    themeOptionLabel(theme).tag(theme)
                }
            } label: {
                Text(L10n.string("主題"))
            }
            .pickerStyle(.inline)
            .labelsHidden()
        } header: {
            SettingsSectionHeader(title: L10n.string("外觀"), icon: "paintpalette")
        }
    }

    private func themeOptionLabel(_ theme: ReaderTheme) -> some View {
        HStack(spacing: AppSpacing.s2) {
            Label(theme.rawValue, systemImage: theme.icon)
            AppRoundedRect(roundness: AppRoundness.pill)
                .fill(appSkin.readerThemeSwatchColor(theme))
                .frame(
                    width: ReaderMetrics.vocabThemeSwatchWidth,
                    height: ReaderMetrics.vocabThemeSwatchHeight
                )
        }
    }

    /// 主題與標記濃度都走既有 closure（而不是直接寫 binding）：那兩個 closure
    /// 各自帶 `withAnimation(AppMotion.panelState)`，繞過它們等於默默拿掉動畫。
    private var themeSelection: Binding<ReaderTheme> {
        Binding(
            get: { bindings.theme.wrappedValue },
            set: { onSelectTheme($0) }
        )
    }

    private var underlineOpacitySelection: Binding<Double> {
        Binding(
            get: { bindings.underlineOpacity.wrappedValue },
            set: { onSelectUnderlineOpacity($0) }
        )
    }

    // MARK: Highlight

    var vocabHighlightSection: some View {
        Section {
            VocabHighlightColorPresetPicker(
                selection: bindings.vocabHighlightColorPreset,
                title: L10n.string("vocab.highlight.color.label")
            )

            Picker(selection: underlineOpacitySelection) {
                ForEach(opacityOptions, id: \.label) { option in
                    Text(L10n.string(option.label)).tag(option.value)
                }
            } label: {
                Text(L10n.string("vocab.highlight.opacity.label"))
            }
            .pickerStyle(.menu)
        } header: {
            SettingsSectionHeader(title: L10n.string("生字標記"), icon: "highlighter")
        }
    }

    // MARK: Debug

    var vocabDebugSection: some View {
        Section {
            Toggle(isOn: bindings.showHitTestingDebug) {
                Text(L10n.string("顯示點擊熱區"))
            }
        } header: {
            SettingsSectionHeader(title: L10n.string("開發者與除錯"), icon: "ladybug")
        } footer: {
            SettingsSectionFooter(L10n.string("用於校正閱讀器點擊熱區。"))
        }
    }
}
#endif
