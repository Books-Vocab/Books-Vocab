import Foundation

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
