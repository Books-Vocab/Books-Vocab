#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

struct VocabHighlightPreferencesTests {
    @Test func legacyUnderlineOpacitySeedsDefaultPreferences() {
        let prefs = VocabHighlightPreferences.resolve(
            storedPresetRaw: nil,
            storedOpacity: nil,
            legacyOpacity: 0.35
        )

        #expect(prefs.colorPreset == .paper)
        #expect(prefs.opacity == 0.35)
        #expect(prefs.bandFraction == 0.32)
    }

    @Test func storedPreferenceWinsOverLegacyOpacity() {
        let prefs = VocabHighlightPreferences.resolve(
            storedPresetRaw: VocabHighlightColorPreset.blue.rawValue,
            storedOpacity: 0.60,
            legacyOpacity: 0.15
        )

        #expect(prefs.colorPreset == .blue)
        #expect(prefs.opacity == 0.60)
    }

    @Test func invalidStoredPresetFallsBackToPaper() {
        let prefs = VocabHighlightPreferences.resolve(
            storedPresetRaw: "unknown",
            storedOpacity: 0.15,
            legacyOpacity: nil
        )

        #expect(prefs.colorPreset == .paper)
        #expect(prefs.opacity == 0.15)
    }

    @Test func readerCssUsesSelectedPresetOpacityAndBandFraction() {
        let prefs = VocabHighlightPreferences(
            colorPreset: .blue,
            opacity: 0.60,
            bandFraction: 0.32
        )
        let css = ReaderContentStyleFactory.make(highlightPreferences: prefs).css()

        #expect(css.contains("--vocab-opacity: 0.6"))
        #expect(css.contains("hsla(212, 32%, 47%, clamp(0, calc(var(--vocab-opacity) * 1.05), 1)) 32%, transparent 32%)"))
        #expect(css.contains("hsla(210, 32%, 64%, clamp(0, calc(var(--vocab-opacity) * 1.45), 1)) 32%, transparent 32%)"))
    }

    @Test func colorPresetTitleKeysAreStable() {
        #expect(VocabHighlightColorPreset.paper.titleKey == "vocab.highlight.color.paper")
        #expect(VocabHighlightColorPreset.blue.titleKey == "vocab.highlight.color.blue")
        #expect(VocabHighlightColorPreset.sage.titleKey == "vocab.highlight.color.sage")
        #expect(VocabHighlightColorPreset.rose.titleKey == "vocab.highlight.color.rose")
        #expect(VocabHighlightColorPreset.custom.titleKey == "自訂")
    }

    @Test func customSRGBIsClampedAndSharedWithReaderCSS() {
        let custom = VocabHighlightSRGB(red: -0.2, green: 0.5, blue: 1.4)
        #expect(custom == VocabHighlightSRGB(red: 0, green: 0.5, blue: 1))

        let preferences = VocabHighlightPreferences(
            colorPreset: .custom,
            opacity: 0.35,
            customSRGB: VocabHighlightSRGB(red: 0.8, green: 0.2, blue: 0.1)
        )
        #expect(preferences.cssColor(for: .light) == "rgb(204, 51, 26)")

        let css = ReaderContentStyleFactory.make(highlightPreferences: preferences).css()
        #expect(css.contains("rgb(204 51 26 / clamp(0, calc(var(--vocab-opacity) * 1.05), 1))"))
        #expect(PodcastVocabHighlightResolver.highlightColor(
            for: preferences,
            colorScheme: .light
        ) == preferences.customSRGB.color)
    }

    @Test func opacityStepClampsAndQuantizesControlValues() {
        #expect(VocabHighlightPreferences.opacityRange == 0...1)
        #expect(VocabHighlightPreferences.opacityStep == 0.05)
        #expect(VocabHighlightPreferences.quantizedOpacity(-0.1) == 0)
        #expect(VocabHighlightPreferences.quantizedOpacity(0.37) == 0.35)
        #expect(VocabHighlightPreferences.quantizedOpacity(1.1) == 1)
    }

    @Test func bridgePlannerEmitsContentStyleOnlyWhenCssChanges() {
        var planner = BridgePlanner()
        let paper = VocabHighlightPreferences(colorPreset: .paper, opacity: 0.35)
        let blue = VocabHighlightPreferences(colorPreset: .blue, opacity: 0.35)

        let initial = planner.makeCommands(from: makeSnapshot(highlightPreferences: paper))
        #expect(contentStyleCommands(in: initial).isEmpty)

        let same = planner.makeCommands(from: makeSnapshot(highlightPreferences: paper))
        #expect(contentStyleCommands(in: same).isEmpty)

        let changed = planner.makeCommands(from: makeSnapshot(highlightPreferences: blue))
        let cssCommands = contentStyleCommands(in: changed)
        #expect(cssCommands.count == 1)
        #expect(cssCommands[0].contains("hsla(212, 32%, 47%"))

        let repeated = planner.makeCommands(from: makeSnapshot(highlightPreferences: blue))
        #expect(contentStyleCommands(in: repeated).isEmpty)
    }

    @Test func readerViewConfigurationUsesHighlightPreferencesAsOpacitySource() {
        let prefs = VocabHighlightPreferences(colorPreset: .sage, opacity: 0.60)
        let configuration = makeConfiguration(highlightPreferences: prefs)

        #expect(configuration.underlineOpacity == 0.60)
        #expect(configuration.contentStyleCSS.contains("--vocab-opacity: 0.6"))
        #expect(configuration.contentStyleCSS.contains("hsla(124, 22%, 46%"))
    }

    private func makeSnapshot(
        highlightPreferences: VocabHighlightPreferences
    ) -> ReadiumNavigatorView.BridgeSnapshot {
        .init(
            lookedUpWords: [],
            bookUniqueWords: [],
            viewConfiguration: makeConfiguration(highlightPreferences: highlightPreferences),
            clearHighlightTrigger: UUID(),
            removeWordTrigger: nil,
            navigateToLocator: nil,
            isInteractionBlocked: false
        )
    }

    private func makeConfiguration(
        highlightPreferences: VocabHighlightPreferences
    ) -> ReaderViewConfiguration {
        let base = ReaderSettings.shared.viewConfiguration(systemColorScheme: .light)
        return ReaderViewConfiguration(
            paperColor: AppColors.paperLight,
            epubPreferences: base.epubPreferences,
            highlightPreferences: highlightPreferences,
            showHitTestingDebug: false,
            swiftUIColorScheme: .light
        )
    }

    private func contentStyleCommands(in commands: [BridgeCommand]) -> [String] {
        commands.compactMap { command in
            guard case .dom(.setContentStyle(let css)) = command else { return nil }
            return css
        }
    }
}
#endif
