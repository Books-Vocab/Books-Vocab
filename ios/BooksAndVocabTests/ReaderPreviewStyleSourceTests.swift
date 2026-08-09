#if os(iOS)
import Foundation
import SwiftUI
import Testing
import UIKit
@testable import BooksAndVocab

/// 閱讀設定的即時預覽（`ReaderSettingsPreviewCard`）宣稱「與閱讀器正文同一份
/// 樣式來源」。閱讀器正文其實是 WKWebView，所以那個宣稱不能靠肉眼比對成立 ——
/// 它成立的方式是：預覽用到的每一個值，都由這裡釘住的同一份來源推導。
///
/// 這組測試就是那份宣稱的憑證。任何一條紅掉，代表預覽已經開始騙人。
struct ReaderPreviewStyleSourceTests {

    // MARK: - 色相：CSS 與原生共讀一張表

    @Test func cssColourIsDerivedFromTheSharedHSLTable() {
        for preset in VocabHighlightColorPreset.allCases {
            for theme in ReaderTheme.allCases {
                let components = preset.hsl(for: theme)
                #expect(
                    preset.cssColor(for: theme)
                        == "\(components.hue), \(components.saturation)%, \(components.lightness)%"
                )
            }
        }
    }

    /// 格式回歸：`hsla()` 吃的是 `43, 34%, 62%`，不是 `43.0, 34.0%, 62.0%`。
    /// 把 HSL 存成 Double 會讓 CSS 靜靜壞掉而沒有人抗議。
    @Test func cssColourKeepsIntegerFormatting() {
        #expect(VocabHighlightColorPreset.paper.cssColor(for: .light) == "43, 34%, 62%")
        #expect(VocabHighlightColorPreset.blue.cssColor(for: .light) == "212, 32%, 47%")
        #expect(VocabHighlightColorPreset.rose.cssColor(for: .dark) == "350, 30%, 68%")
    }

    // MARK: - HSL → HSB 換算

    @Test func hslConvertsToHSBByTheStandardFormula() {
        // paper / light = hsl(43, 34%, 62%)
        //   v  = 0.62 + 0.34 · min(0.62, 0.38) = 0.7492
        //   sv = 2 · (1 − 0.62 / 0.7492)       ≈ 0.34490
        let components = VocabHighlightColorPreset.paper.hsl(for: .light).hsb
        #expect(abs(components.hue - 43.0 / 360) < 0.0001)
        #expect(abs(components.brightness - 0.7492) < 0.0001)
        #expect(abs(components.saturation - 0.34490) < 0.0001)
    }

    @Test func hslEndpointsStayWellDefined() {
        let black = VocabHighlightColorPreset.HSL(hue: 0, saturation: 0, lightness: 0).hsb
        #expect(black.brightness == 0)
        // 亮度 0 時飽和度沒有定義；必須回 0 而不是除以零。
        #expect(black.saturation == 0)

        let white = VocabHighlightColorPreset.HSL(hue: 0, saturation: 0, lightness: 100).hsb
        #expect(white.brightness == 1)
        #expect(white.saturation == 0)
    }

    // MARK: - 每個主題的色帶濃度倍率

    /// 倍率同時餵給 CSS 字串與存起來的屬性。原生預覽讀屬性、WebView 讀字串，
    /// 這條測試釘住兩者永遠是同一個數。
    @Test func storedOpacityMultiplierMatchesTheOneEmbeddedInCSS() {
        let style = ReaderContentStyleFactory.make(
            highlightPreferences: VocabHighlightPreferences(colorPreset: .blue, opacity: 0.35)
        )
        for theme in ReaderTheme.allCases {
            let selection = style.selection(for: theme)
            #expect(
                selection.vocabBackground
                    .contains("var(--vocab-opacity) * \(selection.vocabOpacityMultiplier))")
            )
        }
    }

    @Test func selectionForThemeReturnsTheMatchingThemeBlock() {
        let style = ReaderContentStyleFactory.make(highlightPreferences: .default)
        #expect(style.selection(for: .light) == style.light)
        #expect(style.selection(for: .sepia) == style.sepia)
        #expect(style.selection(for: .dark) == style.dark)
    }

    // MARK: - 字體

    /// `Font.custom` 拿到不存在的名字時**不會報錯**，只會靜靜退回系統字體 ——
    /// 預覽會看起來「還行」但根本不是那個字體。這條測試是唯一擋得住它的東西。
    ///
    /// 特別注意 Crimson Pro：PostScript name 是 `CrimsonProRoman-Regular`，
    /// 與檔名 `CrimsonPro-Regular.ttf` 不同。
    @Test func everyReaderFontResolvesToARegisteredTypeface() {
        for font in ReaderFont.allCases {
            #expect(
                UIFont(name: font.previewFontName, size: 12) != nil,
                "ReaderFont.\(font.rawValue) 的 previewFontName「\(font.previewFontName)」"
                    + "不是已註冊的字體 —— 預覽會靜靜退回系統字體"
            )
        }
    }

    // MARK: - 主題紙色 / 墨色

    /// **這是 regression pin，不是 cross-check** —— 名字要講實話。
    ///
    /// 它只釘住 `ReaderTheme` 那張 theme→顏色表的當前值；它**不**證明送進
    /// WebView 的背景與之相同（那要跑 `viewConfiguration(systemColorScheme:)`，
    /// 而它讀 `AppAppearanceStore.shared`，測試環境無從固定 selection），
    /// 也**不**證明墨色仍等於 Readium 主題前景（那份 CSS 在 SPM bundle 裡，
    /// 不在版控內，測試搆不到）。改主題色時本測試會提醒你順手回頭確認來源。
    @Test func themePaperAndInkTablesStayPinnedToTheirTokens() {
        #expect(ReaderTheme.light.paperColor == AppColors.paperLight)
        #expect(ReaderTheme.sepia.paperColor == AppColors.paperSepia)
        #expect(ReaderTheme.dark.paperColor == AppColors.paperDark)

        // 墨色來源：ReadiumCSS default / sepia = #121212、night = #FEFEFE。
        #expect(ReaderTheme.light.inkColor == AppColors.readerInkLight)
        #expect(ReaderTheme.sepia.inkColor == AppColors.readerInkLight)
        #expect(ReaderTheme.dark.inkColor == AppColors.readerInkDark)
    }

    /// 這條才真的跨過 `viewConfiguration` —— 釘住「送進 WebView 的背景色就是
    /// 該主題的 paperColor」，不管中間換了幾手。
    @Test func viewConfigurationPaperComesFromTheResolvedThemesPaperColor() {
        let settings = ReaderSettings.shared
        for scheme in [ColorScheme.light, .dark] {
            let configuration = settings.viewConfiguration(systemColorScheme: scheme)
            let resolved = settings.resolvedTheme(systemColorScheme: scheme)
            #expect(configuration.paperColor == resolved.paperColor)
        }
    }
}
#endif
