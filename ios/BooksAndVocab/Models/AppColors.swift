//
//  AppColors.swift
//  Books & Vocab
//
//  ⚠️  使用範圍：Reader 功能 + 全域 UI（ErrorBanner、App tint）
//  ─────────────────────────────────────────────────────────────────────
//  此檔案 *不是* Vocabulary UI 的顏色來源。
//  Vocabulary 功能的所有顏色請透過 @Environment(\.appSkin) 取得，
//  其背後由 AppTheme → AppSkin.themed() 組裝而成。
//
//  設計哲學：Notion-inspired Palette + 極淡奶黃 CTA / 灰階 chrome / Morandi 藍被動
//    · 表面近白／中性深灰 — 純淨、扁平，不靠重陰影靠 border 分層
//    · 暖近黑文字（#37352F）取代純黑，承襲 Notion 的溫潤閱讀感
//    · CTA 採極淡奶黃（brandHero #FCDE9A pastel cream，兩種 mode 同色）
//    · Chrome（tint：tab bar / nav button / toolbar）採灰階（tintLight #37352F /
//      tintDark #E6E6E3）— 奶黃不用在「永遠在那」的 chrome 上，避免稀釋 CTA 訊號
//    · 次色保留 Morandi grey-blue（accent #4D7396）— 連結、info、被動點綴
//    · 對比採分級制：正文 ≥4.5:1、metadata ≥3:1、裝飾 ~2.5:1
//    · 極淡奶黃 + 白字對比 ~1.3:1 fail AA → onBrandHero 採深炭灰 #1C1A17 (~13:1)
//  ─────────────────────────────────────────────────────────────────────
//  顏色分組（依使用方）
//    [Reader]  paper*, highlightMarkCSS（ReaderSettings 使用）
//    [Reader]  accent, saved, destructive, warning（TranslationPanel 使用）
//    [Global]  tint（BooksAndVocabApp 注入 SwiftUI tint）
//  ─────────────────────────────────────────────────────────────────────

import SwiftUI

// MARK: - Notion-inspired 色彩 Token（Reader ＆ 全域）

enum AppColors {

    // ── 紙張背景色 ────────────────────────────────────────────────────
    static let paperLight     = Color(red: 0.984, green: 0.980, blue: 0.973)
    static let paperSepia     = Color(red: 0.98, green: 0.965, blue: 0.94)
    static let paperSepiaDeep = Color(red: 0.96, green: 0.93, blue: 0.87)
    static let paperDark      = Color(red: 0.098, green: 0.098, blue: 0.098)

    // ── 閱讀器正文墨色 ────────────────────────────────────────────────
    // 從**出貨的 Readium 主題**量到的，不是配的：ReadiumCSS 的 `--RS__textColor`
    // 在 default / sepia 是 #121212、在 night 是 #FEFEFE
    // （Readium_ReadiumNavigator.bundle/Assets/Static/readium-css/
    //  ReadiumCSS-before.css:281、ReadiumCSS-after.css:247/321）。
    // App 只覆寫背景（`EPUBPreferences.backgroundColor` ← paper*），墨色沿用
    // Readium 主題，所以閱讀設定的原生預覽要對得上就得用這兩個值。
    static let readerInkLight = Color(red: 0.071, green: 0.071, blue: 0.071) // #121212
    static let readerInkDark  = Color(red: 0.996, green: 0.996, blue: 0.996) // #FEFEFE

    // ── 主題強調色（Morandi grey-blue · 取代 Notion 連結藍）─────────────
    // light: #4D7396（~4.99:1 on 白卡） · 由原 #3078A1 降飽和度至 ~36%
    // dark:  #85A4C2（~6.77:1 on 深灰頁面 #191919） · 由原 #5E9FD0 降飽和度至 ~30%
    // 實測對比由 BooksAndVocabTests/WCAGContrastTests.swift 鎖住。
    static let accentLight = Color(red: 0.302, green: 0.451, blue: 0.588)
    static let accentDark  = Color(red: 0.522, green: 0.643, blue: 0.761)

    // ── Brand Hero（極淡奶黃 / pastel cream · 主行動色 CTA）──────────
    // 用於主要 CTA、登入、Today Review 啟動鍵。色相：剛打發奶油 / 紙紋淺金。
    // 兩種 mode 用同一色 `#FCDE9A` — 單一品牌色 invariant，跨 theme 一致。
    // onBrandHero (#1C1A17) 對比 ~13.5:1 ✓ AAA pass（兩模式相同）。
    // 為何不用白字：白字 + #FCDE9A = ~1.3:1 fail AA → 強制走 dark fg。
    // 取捨：在白卡片(#FFFFFF) 上對比僅 ~1.3:1，按鈕略低調 — 設計用意是
    // 「淡淡的黃」、不搶眼。CTA 重量改靠形狀/字重撐起，不靠飽和度。
    static let brandHeroLight = Color(red: 0.988, green: 0.871, blue: 0.604) // #FCDE9A
    static let brandHeroDark  = Color(red: 0.988, green: 0.871, blue: 0.604) // #FCDE9A (同 light)

    // ── On-Brand-Hero 前景（深炭灰，取代 .white）─────────────────────
    // 為何不再用 .white：奶黃 brandHero 上的白字對比 ~3.4:1 fail AA。
    // 改採深炭灰 (#1C1A17)，光暗模式皆對比 ≥5.1:1 ✓ AA。
    // 此 token 與 theme 無關 — 兩種 mode 都用同一色（onBrandHero 是 brandHero 的
    // 配對前景，與 page palette 解耦）。
    static let onBrandHero = Color(red: 0.110, green: 0.102, blue: 0.090) // #1C1A17

    // ── 資訊色（Morandi blue · 與 accent 同色系）──────────────────────
    // 用於 info banner、提示訊息、tooltip 等中性提示
    static let infoLight = Color(red: 0.302, green: 0.451, blue: 0.588)
    static let infoDark  = Color(red: 0.522, green: 0.643, blue: 0.761)

    // ── 翻譯文字色（暖棕墨水）─────────────────────────────────────────
    // Reader 翻譯面板專用，與正文區隔
    static let translationLight = Color(hue: 22/360, saturation: 0.26, brightness: 0.62)
    static let translationDark  = Color(hue: 25/360, saturation: 0.25, brightness: 0.70)

    // ── 成功色（Notion 綠）────────────────────────────────────────────
    // light: #3B7A3B（~4.8:1）  dark: #6FB36F（~6.6:1）
    static let savedLight = Color(red: 0.231, green: 0.478, blue: 0.231)
    static let savedDark  = Color(red: 0.435, green: 0.702, blue: 0.435)

    // ── 危險色（Notion 紅）────────────────────────────────────────────
    // light: #B5403A（~5.2:1）  dark: #E0726B（~5.3:1）
    static let destructiveLight = Color(red: 0.710, green: 0.251, blue: 0.227)
    static let destructiveDark  = Color(red: 0.878, green: 0.447, blue: 0.420)

    // ── 警告色（Notion 琥珀）──────────────────────────────────────────
    // light: #8C6014（~5.1:1）  dark: #D9A441（~7.3:1）
    static let warningLight = Color(red: 0.549, green: 0.376, blue: 0.078)
    static let warningDark  = Color(red: 0.851, green: 0.643, blue: 0.255)

    // ── App 全域 Tint（灰階 chrome）─────────────────────────────────
    // tint = SwiftUI `.tint` 的注入色，影響選中 tab、nav button、toolbar
    // item 等「導覽 chrome」。**刻意不採奶黃** — 奶黃 brandHero 保留給真正
    // 的 CTA(到期複習、開始 review 等)，chrome 走 primaryText 灰階以提升
    // 可讀性、避免「滿屏都是黃」稀釋 CTA 訊號。
    // light: #37352F (= primaryText.light)
    // dark:  #E6E6E3 (= primaryText.dark)
    static let tintLight = Color(red: 0.216, green: 0.208, blue: 0.184)
    static let tintDark  = Color(red: 0.902, green: 0.902, blue: 0.890)

    // ── Chart Highlight（中淡奶黃，stats 頁填色用）──────────────────────
    // brandHero `#FCDE9A` 對白底僅 ~1.3:1，做 heatmap/forecast/calendar 填色
    // 會「肉眼看不到」。Chart 維持奶黃家族但稍深至 `#F0CA89` —
    // 對白底 ~1.6:1 (低調但比 brandHero 醒一階)、對深 card ~9:1 ✓ AAA。
    // 注意：未達 WCAG 3:1 graphical（白底場景），由 user picked，承受 light
    // mode 圖表偏淡的視覺取捨；dark mode 對比強。
    // 用於 VocabActivityHeatmap、VocabForecastChart、VocabCalendarGrid、
    // StatsPresenter 內的 metric icon。
    static let chartHighlight = Color(red: 0.941, green: 0.792, blue: 0.537) // #F0CA89

    // ── 暖中性棕（Preview 場景頁底漸層用）────────────────────────────────
    static let warmNeutral = Color(hue: 30/360, saturation: 0.18, brightness: 0.62)

    // ── Highlight Mark (paper-style 螢光筆) ──────────────────────────────
    static let highlightMark = Color(hue: 45/360, saturation: 0.50, brightness: 0.95)
}

enum AppBrandColors {
    static let googleRed = Color(red: 0.87, green: 0.19, blue: 0.19)
    static let appleBlack = Color.black
}

// MARK: - 環境感知

extension AppColors {
    static func theme(_ scheme: ColorScheme) -> AppTheme {
        AppTheme.resolve(for: scheme)
    }

    static func accent(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? accentDark : accentLight
    }

    static func translation(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? translationDark : translationLight
    }

    static func saved(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? savedDark : savedLight
    }

    static func destructive(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? destructiveDark : destructiveLight
    }

    static func warning(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? warningDark : warningLight
    }

    static func brandHero(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? brandHeroDark : brandHeroLight
    }

    static func info(_ scheme: ColorScheme) -> Color {
        scheme == .dark ? infoDark : infoLight
    }
}

// MARK: - Web CSS Token

extension AppColors {
    // Morandi grey-blue (hue 212, 與 accentLight/Dark 同色相) — Reader 內 web-rendered
    // 詞彙底線高光。雖然 Phase 1b 將主色換奶黃，此處保留藍色 — vocab highlight 屬於
    // 「被動裝飾」(accent family)，不是 CTA / interactive，與 link / info 同分類。
    static let vocabHighlightLightCSS = "linear-gradient(to top, hsla(212, 32%, 47%, 0.20) 35%, transparent 35%)"
    static let vocabHighlightDarkCSS  = "linear-gradient(to top, hsla(210, 32%, 64%, 0.20) 35%, transparent 35%)"
    static let vocabHighlightSepiaCSS = "linear-gradient(to top, hsla(22, 28%, 55%, 0.22) 35%, transparent 35%)"
}
