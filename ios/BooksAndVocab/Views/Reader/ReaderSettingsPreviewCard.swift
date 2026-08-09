#if os(iOS)
import SwiftUI

/// 閱讀設定頁的即時預覽（APP-20260809-ca8e30）。
///
/// 對照組是 `ReviewCardLayoutPreviewCard` —— 那張預覽「不是長得像卡片的東西，
/// 它就是卡片」，內部直接掛出貨用的 `ReviewCardView`。**這裡做不到那件事**，
/// 而且理由是結構性的：閱讀器正文是 Readium 跑在 WKWebView 裡排的，設定經
/// `EPUBPreferences` 進去、樣式以 CSS 注入。要在一列表格裡塞一個等價的 WebView
/// 既昂貴又拿不到同一本書的 CSS，那條路換來的不是「更真」而是「更慢且一樣近似」。
///
/// 所以這張預覽的不飄移承諾**不是「同一個 view」，而是「同一批值」**：
///
/// | 看得到的東西 | 讀哪裡 | 與閱讀器的關係 |
/// |---|---|---|
/// | 字體 | `ReaderFont.previewFontName` | 與 `family` 同一個 enum、同一批 TTF |
/// | 字級 | `fontScale` × `baseFontSize` | 倍率就是送進 `EPUBPreferences.fontSize` 的那個 |
/// | 行距 | `lineHeight` | 送進 `EPUBPreferences.lineHeight` 的那個 |
/// | 紙色 / 墨色 | `ReaderTheme.paperColor` / `.inkColor` | 紙色即 WebView 背景；墨色即 ReadiumCSS 前景 |
/// | 生字色帶 | `ReaderContentStyle` | 色相、濃度倍率、色帶高度、圓角都取自產 CSS 的同一個物件 |
///
/// **具名承認兩件事**（別假裝沒有）：
/// 1. `baseFontSize` 是參考基準，不是某本書的實際 pt —— Readium 的 fontSize 是
///    相對倍率，絕對值取決於該 EPUB 自己的 CSS。預覽保證的是方向與幅度。
/// 2. 換行位置與 WebView 不會一致（SwiftUI 排版 ≠ Blink 排版）。
///
/// 頂層 struct、不 inline 進 presenter 的 body：Debug `-Onone` 下主執行緒 1MB
/// stack 會被 inline 的 section tree 撐爆（見 `SettingsPresenter.swift` 檔頭）。
struct ReaderSettingsPreviewCard: View {
    @ObserveInjection private var inject

    /// 這五個就是 `ReaderSettings.viewConfiguration(systemColorScheme:)` 拿去組
    /// `ReaderViewConfiguration` 的同一批輸入。閱讀器多一個旋鈕，這裡就會少一個。
    let font: ReaderFont
    let fontScale: Double
    let lineHeight: Double
    let theme: ReaderTheme
    let vocabHighlightPreferences: VocabHighlightPreferences

    private typealias Metrics = ReaderPresentationMetrics.SettingsPreview

    var body: some View {
        // 產 CSS 的同一個物件；下面色帶的每一個數都從它身上取。
        let contentStyle = ReaderContentStyleFactory.make(
            highlightPreferences: vocabHighlightPreferences
        )
        let selection = contentStyle.selection(for: theme)

        ReaderProseFlowLayout(spacing: wordSpacing, lineSpacing: resolvedLineSpacing) {
            ForEach(Array(Self.tokens.enumerated()), id: \.offset) { _, token in
                proseWord(token, selection: selection)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(Metrics.contentInset)
        .background {
            AppRoundedRect(roundness: Metrics.cardRoundness)
                .fill(theme.paperColor)
        }
        .clipShape(AppRoundedRect(roundness: Metrics.cardRoundness))
        // 一段示範文字不需要被逐字朗讀，整塊當一個元素報「這是預覽」即可。
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(L10n.string("reader.settings.preview.accessibilityLabel"))
        .accessibilityIdentifier("reader.settings.preview")
        .enableInjection()
    }

    // MARK: - 由設定推導的度量

    /// 送進 `EPUBPreferences.fontSize` 的是倍率，這裡把它落在參考基準上。
    private var resolvedFontSize: CGFloat {
        Metrics.baseFontSize * CGFloat(fontScale)
    }

    /// CSS 的 `line-height: L` 指的是**整個行盒** = L × 字級；SwiftUI 的
    /// `lineSpacing` 則是加在字體自然行高**之外**的量。兩者差的正是字體內在
    /// 行高，所以要扣掉才會是同一種鬆緊 —— 直接把 L 當 lineSpacing 用會鬆到
    /// 不成比例。
    ///
    /// **死區**：滑桿範圍是 1.0…2.5，而扣掉內在行高後 L ≤ 1.2 全部夾成 0，
    /// 所以前 13% 的行程預覽不會動（WebView 那邊仍會更緊，因為 CSS 可以把行盒
    /// 壓到比字體自然行高更小，SwiftUI 的 lineSpacing 不能為負）。這是近似的
    /// 代價，不是 bug；要消掉它得改用 attributed string 的 lineHeightMultiple。
    private var resolvedLineSpacing: CGFloat {
        max(0, resolvedFontSize * (CGFloat(lineHeight) - Metrics.intrinsicLineHeightRatio))
    }

    /// 詞距跟著字級縮放，否則放大字級時字會擠在一起。
    private var wordSpacing: CGFloat {
        resolvedFontSize * Metrics.wordSpacingRatio
    }

    // MARK: - 繪製

    @ViewBuilder
    private func proseWord(
        _ token: ProseToken,
        selection: ReaderContentStyle.ThemeSelectionStyle
    ) -> some View {
        let base = Text(token.text)
            .font(.custom(font.previewFontName, size: resolvedFontSize))
            .foregroundStyle(theme.inkColor)

        switch token.emphasis {
        case .none, .active:
            // `.active` 是「剛點到的字」那個瞬時狀態，不由任何設定控制，
            // 預覽裡不製造它。
            base
        case .vocab:
            base.background(alignment: .bottom) { highlightBand(selection: selection) }
        }
    }

    /// 生字色帶。色相與濃度與 CSS 的 `linear-gradient(...)` 是**同一組輸入**：
    /// 色相 `color(for:)` ↔ `cssColor(for:)`（同一張 HSL 表）、
    /// 濃度 `opacity × vocabOpacityMultiplier` ↔ `calc(var(--vocab-opacity) * M)`
    /// （同一個 Double）。
    ///
    /// **高度只是同名，不是等量**：CSS 的 `\(band)%` 量的是背景盒（≈ 行盒，
    /// 會隨 line-height 變動）的百分比，這裡量的是字級的百分比。兩者在
    /// lineHeight = 1.4 附近相近，在 2.5 時可以差到近兩倍。色帶粗細因此屬於
    /// 「示意」而非「對位」—— 顏色與濃度才是這張預覽真正保證的東西。
    private func highlightBand(
        selection: ReaderContentStyle.ThemeSelectionStyle
    ) -> some View {
        let preferences = vocabHighlightPreferences
        // CSS 端是 `clamp(0, …, 1)`；這裡照抄那個夾擠，不自己另外決定上下界。
        let opacity = min(1, max(0, preferences.opacity * selection.vocabOpacityMultiplier))

        return AppRoundedRect(roundness: Metrics.bandRoundness)
            .fill(preferences.colorPreset.color(for: theme).opacity(opacity))
            .frame(height: resolvedFontSize * CGFloat(preferences.bandFraction))
            .padding(.horizontal, -Metrics.bandOverhang)
    }
}

// MARK: - 示範內文

extension ReaderSettingsPreviewCard {
    /// 一段自有（非版權）英文散文，內含一個被標記的生字，讓「生字標記」那一節
    /// 的顏色與濃度有東西可看 —— 沒有標記字的話那兩個控制項等於沒有預覽。
    ///
    /// 刻意**不**走 `FixtureDatasetStore`：那條路只認 `KG_FIXTURE_DATASET_*`
    /// 環境變數，正式 App 沒有，會當場崩（同 `ReviewCardLayoutPreviewCard`
    /// 檔頭記的那個坑）。
    // i18n-allow: 示範內文是英文閱讀素材本身，不隨介面語言翻譯
    static let sampleParagraph =
        "She kept the letter for years, less for what it said than for the "
        + "quiet, deliberate hand that had written it."

    // i18n-allow: 被標記的示範生字是英文學習素材本身
    static let sampleVocabWords: Set<String> = ["deliberate"]

    /// 斷詞是純函式且與行銷截圖共用，不另寫第二份。
    static let tokens: [ProseToken] = ReaderProseTokenizer.tokens(
        paragraph: sampleParagraph,
        vocab: sampleVocabWords,
        active: []
    )
}

// MARK: - Preview

#Preview("Reader Settings Preview / Sepia 預設") {
    AppThemeContainer {
        Form {
            Section {
                ReaderSettingsPreviewCard(
                    font: .serif,
                    fontScale: 1.0,
                    lineHeight: 1.4,
                    theme: .sepia,
                    vocabHighlightPreferences: .default
                )
            }
        }
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("Reader Settings Preview / Dark 放大") {
    AppThemeContainer {
        Form {
            Section {
                ReaderSettingsPreviewCard(
                    font: .mono,
                    fontScale: 2.0,
                    lineHeight: 2.5,
                    theme: .dark,
                    vocabHighlightPreferences: VocabHighlightPreferences(
                        colorPreset: .rose,
                        opacity: 0.60
                    )
                )
            }
        }
    }
    .preferredColorScheme(.dark)
    .environmentObject(AppAppearanceStore.preview)
}
#endif
