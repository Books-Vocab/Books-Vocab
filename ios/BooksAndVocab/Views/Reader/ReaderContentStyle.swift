#if os(iOS)
import SwiftUI

struct ReaderContentStyle: Equatable {
    struct ThemeSelectionStyle: Equatable {
        let activeOutline: String
        let activeBackground: String
        let vocabBackground: String
    }

    let pageGutterTop: Int
    let pageGutterBottom: Int
    let vocabBorderRadius: Int
    let activeBorderRadius: Int
    let highlightPreferences: VocabHighlightPreferences
    let light: ThemeSelectionStyle
    let sepia: ThemeSelectionStyle
    let dark: ThemeSelectionStyle

    func css() -> String {
        """
        :root {
            --RS__pageGutterTop: \(pageGutterTop)px !important;
            --RS__pageGutterBottom: \(pageGutterBottom)px !important;
            --vocab-opacity: \(highlightPreferences.opacity);
        }

        .active-word {
            outline: \(light.activeOutline);
            outline-offset: 1.5px;
            border-radius: \(activeBorderRadius)px;
            background: \(light.activeBackground) !important;
        }
        .vocab-word {
            background: \(light.vocabBackground);
            border-radius: \(vocabBorderRadius)px;
        }
        .active-word.vocab-word {
            outline: \(light.activeOutline);
            outline-offset: 1.5px;
            background: \(light.activeBackground) !important;
        }
        .active-word .vocab-word {
            background: \(light.activeBackground) !important;
        }

        :root[data-readium-theme="sepia"] .active-word {
            outline: \(sepia.activeOutline);
            outline-offset: 1.5px;
            background: \(sepia.activeBackground) !important;
        }
        :root[data-readium-theme="sepia"] .vocab-word {
            background: \(sepia.vocabBackground);
        }
        :root[data-readium-theme="sepia"] .active-word.vocab-word {
            outline: \(sepia.activeOutline);
            outline-offset: 1.5px;
            background: \(sepia.activeBackground) !important;
        }
        :root[data-readium-theme="sepia"] .active-word .vocab-word {
            background: \(sepia.activeBackground) !important;
        }

        :root[data-readium-theme="dark"] .active-word {
            outline: \(dark.activeOutline);
            outline-offset: 1.5px;
            background: \(dark.activeBackground) !important;
        }
        :root[data-readium-theme="dark"] .vocab-word {
            background: \(dark.vocabBackground);
        }
        :root[data-readium-theme="dark"] .active-word.vocab-word {
            outline: \(dark.activeOutline);
            outline-offset: 1.5px;
            background: \(dark.activeBackground) !important;
        }
        :root[data-readium-theme="dark"] .active-word .vocab-word {
            background: \(dark.activeBackground) !important;
        }
        """
    }
}

enum ReaderContentStyleFactory {
    static func make(highlightPreferences: VocabHighlightPreferences = .default) -> ReaderContentStyle {
        .vocab(highlightPreferences: highlightPreferences)
    }
}

enum ReaderPresentationMetrics {
    enum Overlay {
        static let loadingSpacing: CGFloat = 14
        static let loadingHorizontalInset: CGFloat = 28
        static let loadingVerticalInset: CGFloat = 20
        static let loadingMaxWidth: CGFloat = 320
        static let loadingOuterInset: CGFloat = 20
        static let progressBarWidth: CGFloat = 80
        static let progressBarHeight: CGFloat = 3
        static let progressTextWidth: CGFloat = 30
        static let progressHorizontalInset: CGFloat = 16
        static let progressVerticalInset: CGFloat = 10
        static let topInset: CGFloat = 8
        static let bottomInset: CGFloat = 8
        static let panelMaxWidth: CGFloat = 520
        static let trailingInspectorMaxWidth: CGFloat = 460
    }

    /// Max content widths for regular-layout (Mac/iPad) inline panels, kept
    /// here so the per-presentation getters reference named constants rather
    /// than scattering bare literals.
    enum RegularPanel {
        static let tocContentMaxWidth: CGFloat = 560
        static let tocStateCardMaxWidth: CGFloat = 440
        static let notebookPickerContentMaxWidth: CGFloat = 500
    }

    enum Header {
        static let compactSpacing: CGFloat = 8
        static let contentHorizontalInsetExpanded: CGFloat = 14
        static let contentVerticalInset: CGFloat = 10
        static let outerHorizontalInset: CGFloat = 20
        static let outerTopInset: CGFloat = 8
        static let titleMaxWidth: CGFloat = 160
        static let titleMaxWidthRegular: CGFloat = 300
        static let compactProgressInsetHorizontal: CGFloat = 10
        static let compactProgressInsetVertical: CGFloat = 8
    }

    enum Preview {
        static let blockSpacing: CGFloat = 18
        static let blockHeightTall: CGFloat = 12
        static let blockHeightShort: CGFloat = 10
        /// 骨架文字條圓度(無因次 t)。條高 10–12pt，短邊遠小於 30pt → pill。
        static let blockRoundness: CGFloat = AppRoundness.pill
        static let topInset: CGFloat = 120
        static let horizontalInset: CGFloat = 28
        static let bottomInset: CGFloat = 60
        static let trailingStep: CGFloat = 28
        static let paperOpacityTop: Double = 0.96
        static let paperOpacityMid: Double = 0.88
        static let paperOpacityFloor: Double = 0.08
        static let textBlockEmphasisOpacity: Double = 0.22
        static let textBlockBaseOpacity: Double = 0.12
    }
}

enum ReaderOverlayPanelPlacement: Equatable {
    case centeredBottom
    case trailingInspector

    init(layoutMode: LayoutMode) {
        self = layoutMode.usesInlineDetail ? .trailingInspector : .centeredBottom
    }

    var alignment: Alignment {
        switch self {
        case .centeredBottom: return .center
        case .trailingInspector: return .trailing
        }
    }

    var horizontalInset: CGFloat {
        switch self {
        case .centeredBottom: return AppSpacing.s4
        case .trailingInspector: return AppSpacing.s5
        }
    }

    var bottomInset: CGFloat {
        switch self {
        case .centeredBottom: return ReaderPresentationMetrics.Overlay.bottomInset
        case .trailingInspector: return AppSpacing.s5
        }
    }

    var maxWidth: CGFloat {
        switch self {
        case .centeredBottom: return ReaderPresentationMetrics.Overlay.panelMaxWidth
        case .trailingInspector: return ReaderPresentationMetrics.Overlay.trailingInspectorMaxWidth
        }
    }
}

enum ReaderPanelChromeStyle: Equatable {
    case bottomSheet
    case floatingInspector

    init(layoutMode: LayoutMode) {
        self = layoutMode.usesInlineDetail ? .floatingInspector : .bottomSheet
    }

    var showsDragHandle: Bool {
        self == .bottomSheet
    }

    var allowsDragDismiss: Bool {
        self == .bottomSheet
    }

    var contentTopInset: CGFloat {
        switch self {
        case .bottomSheet: return 0
        case .floatingInspector: return AppSpacing.s4
        }
    }
}

enum ReaderTOCPresentation: Equatable {
    case compact
    case regular

    init(layoutMode: LayoutMode) {
        self = layoutMode.usesInlineDetail ? .regular : .compact
    }

    var contentMaxWidth: CGFloat {
        switch self {
        case .compact: return .infinity
        case .regular: return ReaderPresentationMetrics.RegularPanel.tocContentMaxWidth
        }
    }

    var stateCardMaxWidth: CGFloat {
        switch self {
        case .compact: return .infinity
        case .regular: return ReaderPresentationMetrics.RegularPanel.tocStateCardMaxWidth
        }
    }

    var horizontalPadding: CGFloat {
        switch self {
        case .compact: return 0
        case .regular: return AppSpacing.s5
        }
    }
}

enum ReaderNotebookPickerPresentation: Equatable {
    case compact
    case regular

    init(layoutMode: LayoutMode) {
        self = layoutMode.usesInlineDetail ? .regular : .compact
    }

    var contentMaxWidth: CGFloat {
        switch self {
        case .compact: return .infinity
        case .regular: return ReaderPresentationMetrics.RegularPanel.notebookPickerContentMaxWidth
        }
    }

    var horizontalPadding: CGFloat {
        switch self {
        case .compact: return 0
        case .regular: return AppSpacing.s5
        }
    }
}

private extension ReaderContentStyle {
    static func vocab(highlightPreferences: VocabHighlightPreferences) -> ReaderContentStyle {
        ReaderContentStyle(
            pageGutterTop: 76,
            pageGutterBottom: 52,
            vocabBorderRadius: 3,
            activeBorderRadius: 4,
            highlightPreferences: highlightPreferences,
            light: .init(
                activeOutline: "1px solid rgba(121, 111, 90, 0.34)",
                activeBackground: "rgba(186, 171, 137, 0.09)",
                vocabBackground: vocabBackground(
                    preset: highlightPreferences.colorPreset,
                    theme: .light,
                    opacityMultiplier: 1.05,
                    bandFraction: highlightPreferences.bandFraction
                )
            ),
            sepia: .init(
                activeOutline: "1px solid rgba(126, 96, 66, 0.34)",
                activeBackground: "rgba(168, 134, 92, 0.10)",
                vocabBackground: vocabBackground(
                    preset: highlightPreferences.colorPreset,
                    theme: .sepia,
                    opacityMultiplier: 1.08,
                    bandFraction: highlightPreferences.bandFraction
                )
            ),
            dark: .init(
                activeOutline: "1px solid rgba(208, 196, 166, 0.30)",
                activeBackground: "rgba(204, 186, 138, 0.10)",
                vocabBackground: vocabBackground(
                    preset: highlightPreferences.colorPreset,
                    theme: .dark,
                    opacityMultiplier: 1.45,
                    bandFraction: highlightPreferences.bandFraction
                )
            )
        )
    }

    static func vocabBackground(
        preset: VocabHighlightColorPreset,
        theme: ReaderTheme,
        opacityMultiplier: Double,
        bandFraction: Double
    ) -> String {
        let band = Int((bandFraction * 100).rounded())
        return "linear-gradient(to top, hsla(\(preset.cssColor(for: theme)), clamp(0, calc(var(--vocab-opacity) * \(opacityMultiplier)), 1)) \(band)%, transparent \(band)%)"
    }
}
#endif
