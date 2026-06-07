#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `ReaderSettingsPresenter` — the stateless reader
/// settings surface driven by `State` / `Bindings` / closures (no view model).
///
/// `ReaderSettingsPanel` already covers the panel chrome; here we exercise the
/// presenter directly across font/theme/highlight/bounds permutations using a
/// live `@State` scene so sliders & toggles reflect real selections.
enum ReaderSettingsPresenterScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Reader Settings Presenter") {
            Scenario("Default (Serif / Light)", layout: .fill) {
                ReaderSettingsPresenterScene(
                    fontSizeText: "17pt",
                    canDecrease: true,
                    canIncrease: true,
                    lineHeight: 1.4,
                    font: .serif,
                    theme: .light,
                    underlineOpacity: 0.35,
                    highlight: .paper,
                    showHitTesting: false,
                    scrollMode: false
                )
            }

            Scenario("Sepia / Athelas", layout: .fill) {
                ReaderSettingsPresenterScene(
                    fontSizeText: "19pt",
                    canDecrease: true,
                    canIncrease: true,
                    lineHeight: 1.7,
                    font: .athelas,
                    theme: .sepia,
                    underlineOpacity: 0.15,
                    highlight: .sage,
                    showHitTesting: false,
                    scrollMode: false
                )
            }

            Scenario("Dark / Mono / Debug on", layout: .fill) {
                ReaderSettingsPresenterScene(
                    fontSizeText: "21pt",
                    canDecrease: true,
                    canIncrease: true,
                    lineHeight: 1.9,
                    font: .mono,
                    theme: .dark,
                    underlineOpacity: 0.60,
                    highlight: .blue,
                    showHitTesting: true,
                    scrollMode: true
                )
            }

            // Edge: font size clamped to minimum (decrease disabled),
            // underline hidden, smallest line height.
            Scenario("Lower bound clamp", layout: .fill) {
                ReaderSettingsPresenterScene(
                    fontSizeText: "12pt",
                    canDecrease: false,
                    canIncrease: true,
                    lineHeight: 1.2,
                    font: .sans,
                    theme: .light,
                    underlineOpacity: 0.0,
                    highlight: .rose,
                    showHitTesting: false,
                    scrollMode: false
                )
            }

            // Edge: font size clamped to maximum (increase disabled),
            // widest line height, deepest underline.
            Scenario("Upper bound clamp", layout: .fill) {
                ReaderSettingsPresenterScene(
                    fontSizeText: "28pt",
                    canDecrease: true,
                    canIncrease: false,
                    lineHeight: 2.5,
                    font: .serif,
                    theme: .dark,
                    underlineOpacity: 0.60,
                    highlight: .paper,
                    showHitTesting: false,
                    scrollMode: true
                )
            }
        }
    }
}

// MARK: - Scene harness

/// Holds live `@State` so the presenter's bindings (sliders, toggles, pickers)
/// reflect the seeded selection instead of frozen `.constant` values.
private struct ReaderSettingsPresenterScene: View {
    let fontSizeText: String
    let canDecrease: Bool
    let canIncrease: Bool

    @State private var lineHeight: Double
    @State private var font: ReaderFont
    @State private var theme: ReaderTheme
    @State private var underlineOpacity: Double
    @State private var highlight: VocabHighlightColorPreset
    @State private var showHitTesting: Bool
    @State private var scrollMode: Bool

    init(
        fontSizeText: String,
        canDecrease: Bool,
        canIncrease: Bool,
        lineHeight: Double,
        font: ReaderFont,
        theme: ReaderTheme,
        underlineOpacity: Double,
        highlight: VocabHighlightColorPreset,
        showHitTesting: Bool,
        scrollMode: Bool
    ) {
        self.fontSizeText = fontSizeText
        self.canDecrease = canDecrease
        self.canIncrease = canIncrease
        self._lineHeight = State(initialValue: lineHeight)
        self._font = State(initialValue: font)
        self._theme = State(initialValue: theme)
        self._underlineOpacity = State(initialValue: underlineOpacity)
        self._highlight = State(initialValue: highlight)
        self._showHitTesting = State(initialValue: showHitTesting)
        self._scrollMode = State(initialValue: scrollMode)
    }

    var body: some View {
        AppThemeContainer {
            ReaderSettingsPresenter(
                state: .init(
                    fontSizeText: fontSizeText,
                    canDecreaseFontSize: canDecrease,
                    canIncreaseFontSize: canIncrease
                ),
                bindings: .init(
                    lineHeight: $lineHeight,
                    font: $font,
                    theme: $theme,
                    underlineOpacity: $underlineOpacity,
                    vocabHighlightColorPreset: $highlight,
                    showHitTestingDebug: $showHitTesting,
                    scrollMode: $scrollMode
                ),
                onDecreaseFontSize: {},
                onIncreaseFontSize: {},
                onSelectTheme: { theme = $0 },
                onSelectUnderlineOpacity: { underlineOpacity = $0 },
                onDismiss: {}
            )
            .padding()
        }
        .environmentObject(AppAppearanceStore.preview)
    }
}
#endif
