#if os(iOS)
import SwiftUI

// MARK: - Presenter

struct ReaderSettingsPresenter: View {
    @ObserveInjection private var inject
    /// 只剩主題色票還需要 skin；版面寬窄由系統 sheet 的 detents 決定，
    /// 不再自己讀 horizontalSizeClass 換 panel chrome。
    @Environment(\.appSkin) var appSkin

    struct State {
        let fontSizeText: String
        /// 字級**倍率**本身（`fontSizeText` 是它的顯示字串）。即時預覽需要的是
        /// 這個數 —— 它就是送進 `EPUBPreferences.fontSize` 給閱讀器的那一個。
        let fontScale: Double
        let canDecreaseFontSize: Bool
        let canIncreaseFontSize: Bool
        /// 閱讀器**實際會渲染**的主題，給即時預覽用。
        ///
        /// 不可以拿 `bindings.theme` 代替：那個 binding 是給三選一 Picker 的，
        /// 讀的是 `AppAppearanceMode.readerTheme`，它把 `.system` 壓成 `.light`。
        /// 閱讀器本體走的卻是 `resolvedReaderTheme(systemColorScheme:)`。兩者在
        /// 「外觀＝跟隨系統 ＋ 裝置是深色」時會分岔 —— 閱讀器是暗的，預覽卻是
        /// 亮的，正好在使用者最需要相信預覽的地方說謊。
        let previewTheme: ReaderTheme
    }

    struct Bindings {
        let lineHeight: Binding<Double>
        let font: Binding<ReaderFont>
        let theme: Binding<ReaderTheme>
        let underlineOpacity: Binding<Double>
        let vocabHighlightColorPreset: Binding<VocabHighlightColorPreset>
        let showHitTestingDebug: Binding<Bool>
        let scrollMode: Binding<Bool>
    }

    let state: State
    let bindings: Bindings
    let onDecreaseFontSize: () -> Void
    let onIncreaseFontSize: () -> Void
    let onSelectTheme: (ReaderTheme) -> Void
    let onSelectUnderlineOpacity: (Double) -> Void
    /// 恢復預設 —— 與複習卡版面編輯器同形的 toolbar 入口。
    let onResetToDefaults: () -> Void

    /// label 是 **L10n key**（由 `vocabHighlightSection` 丟給 `L10n.string`），
    /// 不是要顯示的字。用中文字面當 key 會與其他畫面的同名字面撞在一起 ——
    /// 「淡」「中」在 Localizable.strings 裡本來就有別的擁有者。
    let opacityOptions: [(label: String, value: Double)] = [
        ("reader.settings.highlight.opacity.hidden", 0.0),
        ("reader.settings.highlight.opacity.light", 0.15),
        ("reader.settings.highlight.opacity.medium", 0.35),
        ("reader.settings.highlight.opacity.strong", 0.60)
    ]

    var body: some View {
        vocabLayout
        .enableInjection()
    }
}

// MARK: - Previews

#Preview("ReaderSettings / Default") {
    AppThemeContainer {
        // 頁面已不自帶 NavigationStack（那是兩個入口各自的 chrome），preview
        // 自己補一層才看得到標題列與 `.primaryAction` 上的重置選單。
        NavigationStack {
            ReaderSettingsPresenter(
                state: .init(
                    fontSizeText: "1x",
                    fontScale: 1.0,
                    canDecreaseFontSize: true,
                    canIncreaseFontSize: true,
                    previewTheme: .light
                ),
                bindings: .init(
                    lineHeight: .constant(1.4),
                    font: .constant(.serif),
                    theme: .constant(.light),
                    underlineOpacity: .constant(0.35),
                    vocabHighlightColorPreset: .constant(.paper),
                    showHitTestingDebug: .constant(false),
                    scrollMode: .constant(false)
                ),
                onDecreaseFontSize: {},
                onIncreaseFontSize: {},
                onSelectTheme: { _ in },
                onSelectUnderlineOpacity: { _ in },
                onResetToDefaults: {}
            )
        }
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("ReaderSettings / Bounds") {
    AppThemeContainer {
        NavigationStack {
            ReaderSettingsPresenter(
                state: .init(
                    fontSizeText: "0.75x",
                    fontScale: 0.75,
                    canDecreaseFontSize: false,
                    canIncreaseFontSize: true,
                    previewTheme: .dark
                ),
                bindings: .init(
                    lineHeight: .constant(2.5),
                    font: .constant(.sans),
                    theme: .constant(.dark),
                    underlineOpacity: .constant(0.0),
                    vocabHighlightColorPreset: .constant(.rose),
                    showHitTestingDebug: .constant(true),
                    scrollMode: .constant(true)
                ),
                onDecreaseFontSize: {},
                onIncreaseFontSize: {},
                onSelectTheme: { _ in },
                onSelectUnderlineOpacity: { _ in },
                onResetToDefaults: {}
            )
        }
    }
    .preferredColorScheme(.dark)
    .environmentObject(AppAppearanceStore.preview)
}
#endif
