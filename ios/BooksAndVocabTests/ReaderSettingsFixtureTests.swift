#if DEBUG
import Foundation
import Testing
@testable import BooksAndVocab

@Suite(.serialized)
struct ReaderSettingsFixtureTests {
    @Test func marketingDemoReplaysReaderPreferenceOverlayOnBothStores() throws {
        let document = try FixtureDatasetStore.decode(Self.marketingDemoData)
        let userDefaults = document.preferences.userDefaults
        let ubiquitous = document.preferences.ubiquitousKeyValueStore

        #expect(userDefaults["reader_settings_font"] == .string("Mono"))
        #expect(userDefaults["reader_settings_fontSize"] == .double(1.25))
        #expect(userDefaults["reader_settings_lineHeight"] == .double(2.1))
        #expect(userDefaults["reader_settings_scrollMode"] == .bool(true))
        #expect(userDefaults["reader_settings_underlineOpacity"] == .double(0.60))
        #expect(userDefaults["vocab_highlight_colorPreset"] == .string("rose"))
        #expect(userDefaults["vocab_highlight_opacity"] == .double(0.60))
        #expect(userDefaults["reader_settings_showHitTestingDebug"] == .bool(false))

        for key in [
            "reader_settings_font",
            "reader_settings_fontSize",
            "reader_settings_lineHeight",
            "reader_settings_scrollMode",
            "reader_settings_underlineOpacity",
            "vocab_highlight_colorPreset",
            "vocab_highlight_opacity",
        ] {
            #expect(ubiquitous[key] == userDefaults[key], "Reader preference (key) must replay identically")
        }
    }

    private static var marketingDemoData: Data {
        get throws {
            let url = URL(fileURLWithPath: #filePath)
                .deletingLastPathComponent() // BooksAndVocabTests
                .deletingLastPathComponent() // ios
                .deletingLastPathComponent() // repo root
                .appendingPathComponent("ops/fixtures/ui_worlds/marketing_demo.json")
            return try Data(contentsOf: url)
        }
    }
}
#endif
