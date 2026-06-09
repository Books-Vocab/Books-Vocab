//
//  AppThemeResolveTests.swift
//  Books & Vocab Tests
//
//  Pins AppTheme.resolve() — the mapping from ColorScheme / AppAppearanceMode
//  to the concrete theme singletons. A regression here silently changes the
//  app's visual identity on launch or after settings changes.
//

import SwiftUI
import Testing
@testable import BooksAndVocab

struct AppThemeResolveTests {

    // MARK: - resolve(for colorScheme:)

    @Test func lightColorSchemeResolvesToLightTheme() {
        #expect(AppTheme.resolve(for: .light) == .light)
    }

    @Test func darkColorSchemeResolvesToDarkTheme() {
        #expect(AppTheme.resolve(for: .dark) == .dark)
    }

    // MARK: - resolve(for mode:systemColorScheme:)

    @Test func systemModeFollowsLightSystem() {
        #expect(AppTheme.resolve(for: .system, systemColorScheme: .light) == .light)
    }

    @Test func systemModeFollowsDarkSystem() {
        #expect(AppTheme.resolve(for: .system, systemColorScheme: .dark) == .dark)
    }

    @Test func lightModeIgnoresSystem() {
        #expect(AppTheme.resolve(for: .light, systemColorScheme: .dark) == .light)
        #expect(AppTheme.resolve(for: .light, systemColorScheme: .light) == .light)
    }

    @Test func sepiaModeReturnsSepiaRegardlessOfSystem() {
        #expect(AppTheme.resolve(for: .sepia, systemColorScheme: .light) == .sepia)
        #expect(AppTheme.resolve(for: .sepia, systemColorScheme: .dark) == .sepia)
    }

    @Test func darkModeIgnoresSystem() {
        #expect(AppTheme.resolve(for: .dark, systemColorScheme: .light) == .dark)
        #expect(AppTheme.resolve(for: .dark, systemColorScheme: .dark) == .dark)
    }

    // MARK: - identity properties

    @Test func lightThemeHasLightColorScheme() {
        #expect(AppTheme.light.colorScheme == .light)
    }

    @Test func darkThemeHasDarkColorScheme() {
        #expect(AppTheme.dark.colorScheme == .dark)
    }

    @Test func sepiaThemeHasLightColorScheme() {
        #expect(AppTheme.sepia.colorScheme == .light)
    }

    @Test func lightThemePalettePageBackgroundIsNotWhite() {
        // A sanity check that the palette values are actually initialised,
        // not accidentally left at system defaults. The exact values are
        // visual design tokens; we only assert they differ from obvious
        // sentinel values.
        let bg = AppTheme.light.palette.pageBackground
        #expect(bg != Color.white)
    }
}
