#if os(iOS)
import Testing
@testable import BooksAndVocab

struct ReaderThemeGlassPickerTests {
    @Test func preservesProductionThemeAccessibilityIdentifiers() {
        #expect(ReaderTheme.allCases.count == 3)
        #expect(
            ReaderTheme.allCases.map { "reader.settings.theme.\($0.rawValue.lowercased())" }
                == [
                    "reader.settings.theme.light",
                    "reader.settings.theme.sepia",
                    "reader.settings.theme.dark"
                ]
        )
    }

    @Test func glassTilesKeepAdaptiveWidthAndHIGHitTarget() {
        #expect(ReaderThemeGlassPickerMetrics.minimumTileWidth >= AppSpacing.s10)
        #expect(ReaderThemeGlassPickerMetrics.minimumHitTarget >= 44)
        #expect(ReaderThemeGlassPickerMetrics.previewHeight > AppSpacing.s7)
    }

    @Test func everyThemeProvidesLocalizedLabelIconAndPaperInkPreview() {
        for theme in ReaderTheme.allCases {
            #expect(!theme.displayName.isEmpty)
            #expect(!theme.icon.isEmpty)
            _ = theme.paperColor
            _ = theme.inkColor
        }
    }
}
#endif
