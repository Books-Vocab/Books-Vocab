#if os(iOS)
//
//  ReaderSettingsPanel.swift
//  Books & Vocab
//
//  Created by Antigravity on 2026/2/25.
//

import SwiftUI

struct ReaderSettingsPanel: View {
    @ObserveInjection private var inject
    @Bindable var settings: ReaderSettings
    @EnvironmentObject private var appearanceStore: AppAppearanceStore
    let onDismiss: () -> Void

    private var presenterState: ReaderSettingsPresenter.State {
        .init(
            fontSizeText: String(format: "%.2gx", settings.fontSize),
            fontScale: settings.fontSize,
            canDecreaseFontSize: settings.fontSize > 0.75,
            canIncreaseFontSize: settings.fontSize < 2.0
        )
    }

    /// 將 AppAppearanceMode 映射到 ReaderTheme 用於 UI 顯示
    private var themeBinding: Binding<ReaderTheme> {
        Binding(
            get: { appearanceStore.selection.readerTheme },
            set: { selectTheme($0) }
        )
    }

    var body: some View {
        panelPresenter
        .enableInjection()
    }

    private var panelPresenter: some View {
        ReaderSettingsPresenter(
            state: presenterState,
            bindings: presenterBindings,
            onDecreaseFontSize: decreaseFontSize,
            onIncreaseFontSize: increaseFontSize,
            onSelectTheme: selectTheme,
            onSelectUnderlineOpacity: selectUnderlineOpacity,
            onResetToDefaults: resetToDefaults,
            onDismiss: onDismiss
        )
    }

    private var presenterBindings: ReaderSettingsPresenter.Bindings {
        .init(
            lineHeight: $settings.lineHeight,
            font: $settings.font,
            theme: themeBinding,
            underlineOpacity: $settings.underlineOpacity,
            vocabHighlightColorPreset: $settings.vocabHighlightColorPreset,
            showHitTestingDebug: $settings.showHitTestingDebug,
            scrollMode: $settings.scrollMode
        )
    }

    private func decreaseFontSize() {
        settings.fontSize = max(0.75, settings.fontSize - 0.125)
    }

    private func increaseFontSize() {
        settings.fontSize = min(2.0, settings.fontSize + 0.125)
    }

    private func selectTheme(_ theme: ReaderTheme) {
        withAnimation(AppMotion.panelState) {
            appearanceStore.setAppearance(AppAppearanceMode(from: theme))
        }
    }

    private func selectUnderlineOpacity(_ value: Double) {
        withAnimation(AppMotion.panelState) {
            settings.underlineOpacity = value
        }
    }

    /// 走與主題 / 標記濃度同一個 `AppMotion.panelState`，所以重置時上方的即時
    /// 預覽是「動畫地」回到預設，不是瞬間跳掉。
    private func resetToDefaults() {
        withAnimation(AppMotion.panelState) {
            settings.resetToDefaults()
        }
    }
}

struct ReaderSettingsPanelPreviewHarness: View {
    @ObserveInjection private var inject
    let initialFontSizeText: String
    let canDecreaseFontSize: Bool
    let canIncreaseFontSize: Bool

    @State private var fontScale: Double = 1.0
    @State private var lineHeight: Double = 1.5
    @State private var font: ReaderFont = .serif
    @State private var theme: ReaderTheme = .sepia
    @State private var underlineOpacity: Double = 0.35
    @State private var vocabHighlightColorPreset: VocabHighlightColorPreset = .paper
    @State private var showHitTestingDebug = false
    @State private var scrollMode = false

    private var state: ReaderSettingsPresenter.State {
        .init(
            fontSizeText: initialFontSizeText,
            fontScale: fontScale,
            canDecreaseFontSize: canDecreaseFontSize,
            canIncreaseFontSize: canIncreaseFontSize
        )
    }

    private var bindings: ReaderSettingsPresenter.Bindings {
        .init(
            lineHeight: $lineHeight,
            font: $font,
            theme: $theme,
            underlineOpacity: $underlineOpacity,
            vocabHighlightColorPreset: $vocabHighlightColorPreset,
            showHitTestingDebug: $showHitTestingDebug,
            scrollMode: $scrollMode
        )
    }

    /// 面板本身現在是一整頁 `NavigationStack + Form`（原生 sheet 內容），
    /// harness 不再需要自己鋪頁面底色或把它推到畫面底部。
    var body: some View {
        ReaderSettingsPresenter(
            state: state,
            bindings: bindings,
            // Catalog / #Preview 也走真的加減，否則預覽卡在 harness 裡是死的，
            // 而「改設定會不會即時反映」正是這個 scenario 要看的事。
            onDecreaseFontSize: { fontScale = max(0.75, fontScale - 0.125) },
            onIncreaseFontSize: { fontScale = min(2.0, fontScale + 0.125) },
            onSelectTheme: { theme = $0 },
            onSelectUnderlineOpacity: { underlineOpacity = $0 },
            onResetToDefaults: resetHarnessToDefaults,
            onDismiss: {}
        )
        .enableInjection()
    }

    /// harness 沒有 `ReaderSettings` 單例可重置（它跑在 Catalog / #Preview 裡，
    /// 不該去動使用者真正的偏好），所以把同一組出廠常數寫回自己的 @State。
    private func resetHarnessToDefaults() {
        withAnimation(AppMotion.panelState) {
            fontScale = ReaderSettings.defaultFontSize
            lineHeight = ReaderSettings.defaultLineHeight
            font = ReaderSettings.defaultFont
            scrollMode = ReaderSettings.defaultScrollMode
            vocabHighlightColorPreset = VocabHighlightPreferences.default.colorPreset
            underlineOpacity = VocabHighlightPreferences.default.opacity
            showHitTestingDebug = ReaderSettings.defaultShowHitTestingDebug
        }
    }
}

#Preview("Reader Settings") {
    AppThemeContainer {
        ReaderSettingsPanelPreviewHarness(
            initialFontSizeText: "1.0x",
            canDecreaseFontSize: true,
            canIncreaseFontSize: true
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Reader Settings / Bounds") {
    AppThemeContainer {
        ReaderSettingsPanelPreviewHarness(
            initialFontSizeText: "0.75x",
            canDecreaseFontSize: false,
            canIncreaseFontSize: true
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}
#endif
