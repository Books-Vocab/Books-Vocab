//
//  ReaderFontTests.swift
//  Books & Vocab Tests
//
//  Pins ReaderFont and ReaderTheme mappings. A regression here silently
//  changes the reader's typography or theme appearance.
//

import Testing
@testable import BooksAndVocab

struct ReaderFontTests {

    // MARK: - ReaderFont rawValue

    @Test func serifRawValue() {
        #expect(ReaderFont.serif.rawValue == "Garamond")
    }

    @Test func crimsonProRawValue() {
        #expect(ReaderFont.crimsonPro.rawValue == "CrimsonPro")
    }

    // MARK: - Legacy persisted-value migration
    //
    // 舊使用者把閱讀字體存成 "Athelas"（Apple OS 字體）。換成 bundled Crimson Pro
    // 後，舊 rawValue 必須仍 decode 到 .crimsonPro，否則設定默默退回預設。

    @Test func legacyAthelasDecodesToCrimsonPro() {
        #expect(ReaderFont.decode("Athelas") == .crimsonPro)
    }

    @Test func decodePassesThroughCurrentRawValues() {
        #expect(ReaderFont.decode("CrimsonPro") == .crimsonPro)
        #expect(ReaderFont.decode("Garamond") == .serif)
        #expect(ReaderFont.decode("Sans") == .sans)
        #expect(ReaderFont.decode("Mono") == .mono)
    }

    @Test func decodeUnknownReturnsNil() {
        #expect(ReaderFont.decode("Nonsense") == nil)
    }

    @Test func sansRawValue() {
        #expect(ReaderFont.sans.rawValue == "Sans")
    }

    @Test func monoRawValue() {
        #expect(ReaderFont.mono.rawValue == "Mono")
    }

    // MARK: - ReaderFont CaseIterable

    @Test func allCasesCount() {
        #expect(ReaderFont.allCases.count == 4)
    }

    @Test func idMatchesRawValue() {
        for font in ReaderFont.allCases {
            #expect(font.id == font.rawValue)
        }
    }
}

struct ReaderThemeTests {

    // MARK: - ReaderTheme rawValue

    @Test func lightRawValue() {
        #expect(ReaderTheme.light.rawValue == "Light")
    }

    @Test func sepiaRawValue() {
        #expect(ReaderTheme.sepia.rawValue == "Sepia")
    }

    @Test func darkRawValue() {
        #expect(ReaderTheme.dark.rawValue == "Dark")
    }

    // MARK: - ReaderTheme icon

    @Test func lightIcon() {
        #expect(ReaderTheme.light.icon == "sun.max.fill")
    }

    @Test func sepiaIcon() {
        #expect(ReaderTheme.sepia.icon == "book.fill")
    }

    @Test func darkIcon() {
        #expect(ReaderTheme.dark.icon == "moon.stars.fill")
    }

    // MARK: - ReaderTheme CaseIterable

    @Test func allCasesCount() {
        #expect(ReaderTheme.allCases.count == 3)
    }

    @Test func idMatchesRawValue() {
        for theme in ReaderTheme.allCases {
            #expect(theme.id == theme.rawValue)
        }
    }
}
