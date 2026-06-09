//
//  AppFontsCascadeTests.swift
//  Books & Vocab Tests
//

import Foundation
import Testing
@testable import BooksBrowser

@Suite(.serialized)
@MainActor
struct AppFontsCascadeTests {

    @Test func test_sans_fallback_for_english_uses_PingFangTC() async throws {
        AppLanguageStore.shared.setLanguage(.english)
        defer { AppLanguageStore.shared.setLanguage(.system) }
        #expect(AppFonts.cjkSansFallbackName(bold: false) == "PingFangTC-Regular")
        #expect(AppFonts.cjkSansFallbackName(bold: true) == "PingFangTC-Semibold")
    }

    @Test func test_sans_fallback_for_zhHans_uses_PingFangSC() async throws {
        AppLanguageStore.shared.setLanguage(.simplifiedChinese)
        defer { AppLanguageStore.shared.setLanguage(.system) }
        #expect(AppFonts.cjkSansFallbackName(bold: false) == "PingFangSC-Regular")
        #expect(AppFonts.cjkSansFallbackName(bold: true) == "PingFangSC-Semibold")
    }

    @Test func test_sans_fallback_for_japanese_uses_Hiragino() async throws {
        AppLanguageStore.shared.setLanguage(.japanese)
        defer { AppLanguageStore.shared.setLanguage(.system) }
        #expect(AppFonts.cjkSansFallbackName(bold: false) == "HiraginoSans-W3")
        #expect(AppFonts.cjkSansFallbackName(bold: true) == "HiraginoSans-W6")
    }

    @Test func test_sans_fallback_for_korean_uses_AppleSDGothic() async throws {
        AppLanguageStore.shared.setLanguage(.korean)
        defer { AppLanguageStore.shared.setLanguage(.system) }
        #expect(AppFonts.cjkSansFallbackName(bold: false) == "AppleSDGothicNeo-Regular")
        #expect(AppFonts.cjkSansFallbackName(bold: true) == "AppleSDGothicNeo-Bold")
    }

    @Test func test_serif_fallback_japanese_uses_HiraMin() async throws {
        AppLanguageStore.shared.setLanguage(.japanese)
        defer { AppLanguageStore.shared.setLanguage(.system) }
        #expect(AppFonts.cjkSerifFallbackName(bold: false) == "HiraMinProN-W3")
        #expect(AppFonts.cjkSerifFallbackName(bold: true) == "HiraMinProN-W6")
    }

    @Test func test_serif_fallback_simplifiedChinese_uses_STSongtiSC() async throws {
        AppLanguageStore.shared.setLanguage(.simplifiedChinese)
        defer { AppLanguageStore.shared.setLanguage(.system) }
        #expect(AppFonts.cjkSerifFallbackName(bold: false) == "STSongti-SC-Regular")
    }
}
