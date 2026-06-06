#if os(iOS)
import Testing
@testable import BooksBrowser

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
}
#endif
