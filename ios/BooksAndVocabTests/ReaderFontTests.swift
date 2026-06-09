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

    @Test func athelasRawValue() {
        #expect(ReaderFont.athelas.rawValue == "Athelas")
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
