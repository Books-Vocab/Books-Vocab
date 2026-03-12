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
    let light: ThemeSelectionStyle
    let sepia: ThemeSelectionStyle
    let dark: ThemeSelectionStyle

    func css() -> String {
        """
        :root {
            --RS__pageGutterTop: \(pageGutterTop)px !important;
            --RS__pageGutterBottom: \(pageGutterBottom)px !important;
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
    static func make(mode: TranslationPanelMode) -> ReaderContentStyle {
        switch mode {
        case .glass:
            return .glass
        case .vocab:
            return .vocab
        }
    }
}

enum ReaderGlassTypography {
    // Reader-only：rounded 24pt bold，維持 rounded 與正文區隔
    static let word = Font.system(size: 24, weight: .bold, design: .rounded)
    // Mono (ElmsSans)
    static let pronunciation = AppFonts.monoNumbers(size: 13)
    static let numericMono = AppFonts.monoNumbers(size: 10)
    static let progressText = AppFonts.monoProgress()
    static let settingsValue = AppFonts.mono(size: 13)
    static let settingsStepSmall = AppFonts.mono(size: 14, bold: true)
    static let settingsStepLarge = AppFonts.mono(size: 22, bold: true)
    // Serif (Athelas + STSongti-TC)
    static let partOfSpeech = AppFonts.caption(weight: .medium)
    static let body = AppFonts.subhead()
    static let translationTitle = AppFonts.serif(size: 20, bold: true)
    static let label = AppFonts.caption()
    static let labelSmall = AppFonts.caption2()
    static let savedStatus = AppFonts.serif(size: 11, bold: true)
    static let headerBackLabel = AppFonts.serif(size: 15)
    static let headerTitle = AppFonts.caption(weight: .medium)
    static let headerAction = AppFonts.serif(size: 15)
    // SF Symbols / 圖示 — 維持 system
    static let iconTiny = Font.system(.caption)
    static let toolbarIcon = Font.callout
    static let headerBackIcon = Font.system(size: 15, weight: .semibold)
    static let headerCollapse = Font.system(size: 14, weight: .semibold)
    static let compactMenuIcon = Font.system(size: 18, weight: .medium)
    static let settingsIcon = Font.system(size: 14)
    static let settingsCloseIcon = Font.system(size: ReaderPresentationMetrics.Settings.closeIconSize)
}

enum ReaderPresentationMetrics {
    enum Panel {
        static let handleWidth: CGFloat = 32
        static let handleHeight: CGFloat = 4
        static let handleTopInset: CGFloat = 8
        static let handleBottomInset: CGFloat = 10
        static let sectionSpacing: CGFloat = 10
        static let horizontalInset: CGFloat = 18
        static let bottomInset: CGFloat = 16
        static let badgeHorizontalPadding: CGFloat = 7
        static let badgeVerticalPadding: CGFloat = 3
        static let messageVerticalInset: CGFloat = 12
        static let statusInsetVertical: CGFloat = 8
        static let statusInsetHorizontal: CGFloat = 10
        static let statusCornerRadius: CGFloat = 10
        static let dividerInsetVertical: CGFloat = 2
        static let explanationInsetVertical: CGFloat = 4
        static let toolbarTopInset: CGFloat = 2
        static let actionButtonSize: CGFloat = 32
        static let cornerRadius: CGFloat = 20
        static let shadowOpacity: Double = 0.06
        static let shadowRadius: CGFloat = 12
        static let shadowY: CGFloat = -3
    }

    enum Settings {
        static let controlHeight: CGFloat = 44
        static let centeredValueWidth: CGFloat = 48
        static let sliderSpacing: CGFloat = 14
        static let sliderValueWidth: CGFloat = 28
        static let optionSpacing: CGFloat = 8
        static let optionLabelSpacing: CGFloat = 6
        static let optionVerticalInset: CGFloat = 12
        static let optionCornerRadius: CGFloat = 10
        static let underlineCornerRadius: CGFloat = 8
        static let underlineVerticalInset: CGFloat = 10
        static let sectionVerticalInset: CGFloat = 4
        static let closeIconSize: CGFloat = 22
        static let selectedFillOpacity: Double = 0.12
        static let selectedStrokeOpacity: Double = 0.1
    }

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
    }

    enum Header {
        static let compactSpacing: CGFloat = 8
        static let contentHorizontalInset: CGFloat = 12
        static let contentHorizontalInsetExpanded: CGFloat = 14
        static let contentVerticalInset: CGFloat = 10
        static let outerHorizontalInset: CGFloat = 20
        static let outerTopInset: CGFloat = 8
        static let buttonSize: CGFloat = 34
        static let compactButtonSize: CGFloat = 44
        static let titleMaxWidth: CGFloat = 160
        static let titleMaxWidthRegular: CGFloat = 300
        static let trailingInset: CGFloat = 4
        static let progressSpacing: CGFloat = 6
        static let compactProgressInsetHorizontal: CGFloat = 10
        static let compactProgressInsetVertical: CGFloat = 8
        static let shadowOpacity: Double = 0.08
        static let expandedShadowRadius: CGFloat = 16
        static let compactShadowRadius: CGFloat = 10
        static let shadowY: CGFloat = 4
    }

    enum Preview {
        static let blockSpacing: CGFloat = 18
        static let blockCornerRadius: CGFloat = 4
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

private extension ReaderContentStyle {
    static let glass = ReaderContentStyle(
        pageGutterTop: 72,
        pageGutterBottom: 48,
        vocabBorderRadius: 2,
        activeBorderRadius: 3,
        light: .init(
            activeOutline: "1px solid rgba(80, 80, 80, 0.40)",
            activeBackground: "rgba(80, 80, 80, 0.04)",
            vocabBackground: "linear-gradient(to top, hsla(215, 30%, 58%, var(--vocab-opacity)) 35%, transparent 35%)"
        ),
        sepia: .init(
            activeOutline: "1px solid rgba(90, 70, 50, 0.40)",
            activeBackground: "rgba(90, 70, 50, 0.05)",
            vocabBackground: "linear-gradient(to top, hsla(22, 28%, 55%, var(--vocab-opacity)) 35%, transparent 35%)"
        ),
        dark: .init(
            activeOutline: "1px solid rgba(200, 195, 185, 0.35)",
            activeBackground: "rgba(200, 195, 185, 0.06)",
            vocabBackground: "linear-gradient(to top, hsla(215, 28%, 70%, clamp(0, calc(var(--vocab-opacity) * 1.6), 1)) 35%, transparent 35%)"
        )
    )

    static let vocab = ReaderContentStyle(
        pageGutterTop: 76,
        pageGutterBottom: 52,
        vocabBorderRadius: 3,
        activeBorderRadius: 4,
        light: .init(
            activeOutline: "1px solid rgba(121, 111, 90, 0.34)",
            activeBackground: "rgba(186, 171, 137, 0.09)",
            vocabBackground: "linear-gradient(to top, hsla(43, 34%, 62%, clamp(0, calc(var(--vocab-opacity) * 1.05), 1)) 32%, transparent 32%)"
        ),
        sepia: .init(
            activeOutline: "1px solid rgba(126, 96, 66, 0.34)",
            activeBackground: "rgba(168, 134, 92, 0.10)",
            vocabBackground: "linear-gradient(to top, hsla(30, 32%, 54%, clamp(0, calc(var(--vocab-opacity) * 1.08), 1)) 32%, transparent 32%)"
        ),
        dark: .init(
            activeOutline: "1px solid rgba(208, 196, 166, 0.30)",
            activeBackground: "rgba(204, 186, 138, 0.10)",
            vocabBackground: "linear-gradient(to top, hsla(41, 30%, 66%, clamp(0, calc(var(--vocab-opacity) * 1.45), 1)) 32%, transparent 32%)"
        )
    )
}
