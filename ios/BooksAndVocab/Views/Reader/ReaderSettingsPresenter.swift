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
    let onDismiss: () -> Void

    let opacityOptions: [(label: String, value: Double)] = [
        ("隱藏", 0.0),
        ("淡", 0.15),
        ("中", 0.35),
        ("深", 0.60)
    ]

    var body: some View {
        vocabLayout
        .enableInjection()
    }
}

// MARK: - Previews

#Preview("ReaderSettings / Default") {
    AppThemeContainer {
        ReaderSettingsPresenter(
            state: .init(
                fontSizeText: "17pt",
                fontScale: 1.0,
                canDecreaseFontSize: true,
                canIncreaseFontSize: true
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
            onResetToDefaults: {},
            onDismiss: {}
        )
        .padding()
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("ReaderSettings / Bounds") {
    AppThemeContainer {
        ReaderSettingsPresenter(
            state: .init(
                fontSizeText: "0.75x",
                fontScale: 0.75,
                canDecreaseFontSize: false,
                canIncreaseFontSize: true
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
            onResetToDefaults: {},
            onDismiss: {}
        )
    }
    .preferredColorScheme(.dark)
    .environmentObject(AppAppearanceStore.preview)
}
#endif
