#if os(iOS)
import SwiftUI
import UIKit

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

    /// **一頁，不含 chrome** —— 沒有自己的 `NavigationStack`、沒有「完成」。
    ///
    /// 這是為了讓同一頁能掛在兩個入口下，與 `ReviewCardLayoutEditor` 完全同構：
    /// 從閱讀器進來時由 `ReaderSettingsPanelSheet` 補上 stack 與完成鍵；從
    /// 設定▸偏好 進來時直接被 `navigationDestination` push，用既有的返回鍵。
    /// 頁面自己帶 `NavigationStack` 的話，push 進設定會變成雙層導覽列。
    var vocabLayout: some View {
        Form {
            vocabPreviewSection
            vocabTypographySection
            vocabAppearanceSection
            vocabHighlightSection
            #if DEBUG
            vocabDebugSection
            #endif
        }
        .navigationTitle(L10n.string("reader.settings.title"))
        .inlineNavigationBarTitle()
        .toolbar {
            ToolbarItem(placement: .primaryAction) { resetMenu }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("reader.settingsPanel")
    }

    // MARK: Reset

    /// 與 `ReviewCardLayoutEditor.resetMenu` 同形：`.primaryAction` 上一個
    /// 逆時針箭頭選單，唯一一個 destructive 項目，identifier 走同一個
    /// `<scope>.resetMenu` 後綴慣例。兩頁的重置手感因此一致。
    private var resetMenu: some View {
        Menu {
            Button(L10n.string("reader.settings.reset.all"), role: .destructive) {
                onResetToDefaults()
            }
            .accessibilityIdentifier("reader.settings.reset.all")
        } label: {
            Image(systemName: "arrow.counterclockwise")
        }
        .accessibilityLabel(L10n.string("reader.settings.reset"))
        .accessibilityIdentifier("reader.settings.resetMenu")
    }

    // MARK: Preview

    /// 即時預覽擺在控制項**之前**：先讓人看到現在長什麼樣，再讓人動旋鈕。
    ///
    /// **與複習卡版面編輯器順序相反，這是刻意的不是不一致**（別「對齊」回去）。
    /// 共用的規則是「預覽緊貼它所控制的東西」：這一頁的控制項全頁共用同一份
    /// `ReaderSettings`，所以預覽只需要一張、擺頁首涵蓋全部；`ReviewCardLayoutEditor`
    /// 的預覽是**該複習方向專屬**的（辨識 / 產出各一張，`VocabularyCardMode`；每張
    /// 本身都已兩面都畫），所以它擺在各自 Picker 的
    /// 正下方（見 `ReviewCardLayoutEditor.swift:directionSection`）。
    ///
    /// 每一格都直接讀 binding 的當前值，沒有 draft、沒有 snapshot ——
    /// 所以它必然與正下方那些控制項一致，不需要靠誰記得同步。
    var vocabPreviewSection: some View {
        Section {
            ReaderSettingsPreviewCard(
                font: bindings.font.wrappedValue,
                fontScale: state.fontScale,
                lineHeight: bindings.lineHeight.wrappedValue,
                theme: state.previewTheme,
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
                LabeledContent(L10n.string("reader.settings.fontSize")) {
                    Text(state.fontSizeText).monospacedDigit()
                }
            }
            .accessibilityIdentifier("reader.settings.fontSizeStepper")

            VStack(alignment: .leading, spacing: AppSpacing.s1) {
                LabeledContent(L10n.string("reader.settings.lineHeight")) {
                    Text(String(format: "%.1f", bindings.lineHeight.wrappedValue))
                        .monospacedDigit()
                }
                ReaderSettingsLineHeightSlider(value: bindings.lineHeight)
            }

            Picker(selection: bindings.scrollMode) {
                Text(L10n.string("reader.settings.readingMode.paged")).tag(false)
                Text(L10n.string("reader.settings.readingMode.scroll")).tag(true)
            } label: {
                Text(L10n.string("reader.settings.readingMode"))
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("reader.settings.readingMode")
        } header: {
            SettingsSectionHeader(title: L10n.string("reader.settings.section.typography"), icon: "textformat.size")
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
                Text(L10n.string("reader.settings.font"))
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("reader.settings.font")

            themeOptions
        } header: {
            SettingsSectionHeader(title: L10n.string("reader.settings.section.appearance"), icon: "paintpalette")
        }
    }

    private func themeOptionLabel(_ theme: ReaderTheme) -> some View {
        HStack(spacing: AppSpacing.s2) {
            Label(theme.displayName, systemImage: theme.icon)
            AppRoundedRect(roundness: AppRoundness.pill)
                .fill(appSkin.readerThemeSwatchColor(theme))
                .frame(
                    width: ReaderMetrics.vocabThemeSwatchWidth,
                    height: ReaderMetrics.vocabThemeSwatchHeight
                )
        }
    }

    /// An explicit button list keeps each theme choice addressable in UI tests.
    /// SwiftUI's inline Picker does not preserve child accessibility identifiers
    /// in the XCTest hierarchy, making theme counterexamples flaky by construction.
    private var themeOptions: some View {
        VStack(spacing: 0) {
            ForEach(ReaderTheme.allCases) { theme in
                Button {
                    onSelectTheme(theme)
                } label: {
                    HStack(spacing: AppSpacing.s2) {
                        themeOptionLabel(theme)
                        Spacer(minLength: AppSpacing.s2)
                        if bindings.theme.wrappedValue == theme {
                            Image(systemName: "checkmark")
                                .foregroundStyle(.tint)
                                .accessibilityHidden(true)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityIdentifier("reader.settings.theme.\(theme.rawValue.lowercased())")
                .accessibilityAddTraits(bindings.theme.wrappedValue == theme ? .isSelected : [])
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("reader.settings.theme")
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
                title: L10n.string("vocab.highlight.color.label"),
                accessibilityIdentifier: "reader.settings.highlightColor"
            )

            Picker(selection: underlineOpacitySelection) {
                ForEach(opacityOptions, id: \.label) { option in
                    Text(L10n.string(option.label)).tag(option.value)
                }
            } label: {
                Text(L10n.string("vocab.highlight.opacity.label"))
            }
            .pickerStyle(.menu)
            .accessibilityIdentifier("reader.settings.highlightOpacity")
        } header: {
            SettingsSectionHeader(title: L10n.string("reader.settings.section.highlight"), icon: "highlighter")
        }
    }

    // MARK: Debug

    #if DEBUG
    var vocabDebugSection: some View {
        Section {
            Toggle(isOn: bindings.showHitTestingDebug) {
                Text(L10n.string("reader.settings.debug.hitTesting"))
            }
            .accessibilityIdentifier("reader.settings.debug.hitTesting")
        } header: {
            SettingsSectionHeader(title: L10n.string("reader.settings.section.debug"), icon: "ladybug")
        } footer: {
            SettingsSectionFooter(L10n.string("reader.settings.debug.footer"))
        }
    }
    #endif
}

private struct ReaderSettingsLineHeightSlider: View {
    @Binding var value: Double

    private typealias Metrics = ReaderPresentationMetrics.SettingsPreview

    var body: some View {
        VStack(spacing: AppSpacing.microGap) {
            NativeReaderLineHeightSlider(value: $value)

            HStack(spacing: 0) {
                ForEach(Metrics.lineHeightTickValues.indices, id: \.self) { index in
                    Rectangle()
                        .fill(.secondary.opacity(index.isMultiple(of: 5) ? 0.55 : 0.3))
                        .frame(width: 1, height: index.isMultiple(of: 5) ? 6 : 4)

                    if index < Metrics.lineHeightTickCount - 1 {
                        Spacer(minLength: 0)
                    }
                }
            }
            .padding(.horizontal, AppSpacing.s2)
            .accessibilityHidden(true)
        }
    }
}

private struct NativeReaderLineHeightSlider: UIViewRepresentable {
    @Binding var value: Double

    private typealias Metrics = ReaderPresentationMetrics.SettingsPreview

    func makeCoordinator() -> Coordinator {
        Coordinator(parent: self)
    }

    func makeUIView(context: Context) -> UISlider {
        let slider = UISlider(
            frame: .zero
        )
        slider.minimumValue = Float(Metrics.lineHeightRange.lowerBound)
        slider.maximumValue = Float(Metrics.lineHeightRange.upperBound)
        // Let UIKit/XCTest complete interior drags reliably on iOS 26. The
        // coordinator coalesces the valueChanged stream into one quiet-window
        // commit, so the Reader's WebView does not receive every intermediate
        // 0.1 tick while the final value remains a real native interaction.
        slider.isContinuous = true
        slider.accessibilityLabel = L10n.string("reader.settings.lineHeight")
        slider.accessibilityIdentifier = "reader.settings.lineHeight"
        slider.accessibilityValue = Self.accessibilityValue(for: value)
        slider.addTarget(
            context.coordinator,
            action: #selector(Coordinator.valueChanged(_:)),
            for: .valueChanged
        )
        for event in [UIControl.Event.touchUpInside, .touchUpOutside, .touchCancel] {
            slider.addTarget(
                context.coordinator,
                action: #selector(Coordinator.commitValue(_:)),
                for: event
            )
        }
        slider.value = Float(Self.quantized(value))
        return slider
    }

    func updateUIView(_ slider: UISlider, context: Context) {
        context.coordinator.parent = self
        let nextValue = Float(Self.quantized(value))
        if abs(slider.value - nextValue) > 0.0001 {
            slider.setValue(nextValue, animated: false)
        }
        slider.accessibilityValue = Self.accessibilityValue(for: value)
    }

    private static func quantized(_ rawValue: Double) -> Double {
        let clamped = min(
            max(rawValue, Metrics.lineHeightRange.lowerBound),
            Metrics.lineHeightRange.upperBound
        )
        let ticks = ((clamped - Metrics.lineHeightRange.lowerBound) / Metrics.lineHeightStep).rounded()
        return Metrics.lineHeightRange.lowerBound + (ticks * Metrics.lineHeightStep)
    }

    private static func accessibilityValue(for rawValue: Double) -> String {
        String(
            format: "%.1f",
            locale: Locale(identifier: "en_US_POSIX"),
            quantized(rawValue)
        )
    }

    final class Coordinator: NSObject {
        var parent: NativeReaderLineHeightSlider

        init(parent: NativeReaderLineHeightSlider) {
            self.parent = parent
        }

        @objc
        func valueChanged(_ slider: UISlider) {
            let nextValue = Self.quantized(
                Double(slider.value),
                range: Metrics.lineHeightRange,
                step: Metrics.lineHeightStep
            )
            slider.setValue(Float(nextValue), animated: false)
            slider.accessibilityValue = Self.accessibilityValue(for: nextValue)
            pendingValue = nextValue
            scheduleQuietCommit()
        }

        @objc
        func commitValue(_ slider: UISlider) {
            valueChanged(slider)
            parent.value = pendingValue ?? Self.quantized(
                Double(slider.value),
                range: Metrics.lineHeightRange,
                step: Metrics.lineHeightStep
            )
            pendingValue = nil
            quietCommit?.cancel()
            quietCommit = nil
            quietCommitToken = nil
        }

        private var pendingValue: Double?
        private var quietCommit: DispatchWorkItem?
        private var quietCommitToken: UUID?

        private func scheduleQuietCommit() {
            quietCommit?.cancel()
            let token = UUID()
            quietCommitToken = token
            let work = DispatchWorkItem { [weak self] in
                guard let self,
                      self.quietCommitToken == token,
                      let pendingValue = self.pendingValue else { return }
                self.parent.value = pendingValue
                self.pendingValue = nil
                self.quietCommit = nil
                self.quietCommitToken = nil
            }
            quietCommit = work
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.15, execute: work)
        }

        private static func accessibilityValue(for value: Double) -> String {
            String(
                format: "%.1f",
                locale: Locale(identifier: "en_US_POSIX"),
                value
            )
        }

        private static func quantized(
            _ rawValue: Double,
            range: ClosedRange<Double>,
            step: Double
        ) -> Double {
            let clamped = min(max(rawValue, range.lowerBound), range.upperBound)
            let ticks = ((clamped - range.lowerBound) / step).rounded()
            return range.lowerBound + (ticks * step)
        }
    }
}
#endif
