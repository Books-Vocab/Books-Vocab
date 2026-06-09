//
//  AppAppearanceModeTests.swift
//  Books & Vocab Tests
//
//  Pins AppAppearanceMode value mappings. A regression here changes the app's
//  theme or reader appearance silently.
//

import SwiftUI
import Testing
@testable import BooksAndVocab

struct AppAppearanceModeTests {

    // MARK: - colorScheme

    @Test func systemColorSchemeIsNil() {
        #expect(AppAppearanceMode.system.colorScheme == nil)
    }

    @Test func lightColorSchemeIsLight() {
        #expect(AppAppearanceMode.light.colorScheme == .light)
    }

    @Test func sepiaColorSchemeIsLight() {
        #expect(AppAppearanceMode.sepia.colorScheme == .light)
    }

    @Test func darkColorSchemeIsDark() {
        #expect(AppAppearanceMode.dark.colorScheme == .dark)
    }

    // MARK: - readerTheme

    @Test func systemReaderThemeIsLight() {
        #expect(AppAppearanceMode.system.readerTheme == .light)
    }

    @Test func lightReaderThemeIsLight() {
        #expect(AppAppearanceMode.light.readerTheme == .light)
    }

    @Test func sepiaReaderThemeIsSepia() {
        #expect(AppAppearanceMode.sepia.readerTheme == .sepia)
    }

    @Test func darkReaderThemeIsDark() {
        #expect(AppAppearanceMode.dark.readerTheme == .dark)
    }

    // MARK: - init(from: ReaderTheme)

    @Test func initFromLightReturnsLight() {
        #expect(AppAppearanceMode(from: .light) == .light)
    }

    @Test func initFromSepiaReturnsSepia() {
        #expect(AppAppearanceMode(from: .sepia) == .sepia)
    }

    @Test func initFromDarkReturnsDark() {
        #expect(AppAppearanceMode(from: .dark) == .dark)
    }
}
