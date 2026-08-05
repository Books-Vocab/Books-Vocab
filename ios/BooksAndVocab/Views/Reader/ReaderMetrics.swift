//
//  ReaderMetrics.swift
//  Books & Vocab
//
//  Reader feature 專用版面參數(panel handle、settings sheet inset、option padding 等)。
//  從 AppSkin.Metrics 遷出 —— 純幾何常數,語意原生於 Reader feature。
//  cross-feature 借用者:
//    - UIComponents/AppShellComponents.swift(readerSettings header / card padding 共用)
//    - Views/Vocabulary/Components/CollocationExplainSheet.swift(翻譯 sheet 對齊 Reader panel)
//  → 詳見 docs/reference/feature_boundary/vocabulary.md 的 stakeholder 標註。
//

import SwiftUI

enum ReaderMetrics {
    // MARK: - Panel(Reader 主面板的 handle / inset)

    static let panelHorizontalInset: CGFloat = 18
    static let panelBottomInset: CGFloat = 16
    static let panelHandleWidth: CGFloat = 32
    static let panelHandleHeight: CGFloat = 4
    static let panelHandleTopInset: CGFloat = 10
    static let panelHandleBottomInset: CGFloat = 12

    // MARK: - Settings handle

    static let settingsHandleWidth: CGFloat = 48
    static let settingsHandleHeight: CGFloat = 5
    static let settingsHandleTopInset: CGFloat = 12
    static let settingsHandleBottomInset: CGFloat = 14

    // MARK: - Settings layout

    static let settingsHorizontalInset: CGFloat = 18
    static let settingsBottomInset: CGFloat = 20

    // MARK: - Settings header

    static let settingsHeaderSpacing: CGFloat = 14
    static let settingsHeaderBottomInset: CGFloat = 16
    static let settingsHeaderMicroInset: CGFloat = 4

    // MARK: - Settings card / control / option padding

    static let settingsCardPadding: CGFloat = 16
    static let settingsControlHorizontalPadding: CGFloat = 14
    static let settingsControlVerticalPadding: CGFloat = 14

    // MARK: - Settings divider

    /// 設定面板分隔線透明度
    static let settingsDividerOpacity: Double = 0.6

    // MARK: - Vocab settings

    static let vocabValueReadoutWidth: CGFloat = 34
    static let vocabModeToggleMaxWidth: CGFloat = 160
    static let vocabOptionVerticalPadding: CGFloat = 10
    static let vocabThemeSwatchHeight: CGFloat = 8

    // MARK: - Quota bar

    /// 額度進度條圓度(無因次 t)。2pt 高的極細條 → pill;
    /// r = 1 × 2/2 = 1，與舊的絕對 1pt 完全等值。
    static let quotaBarRoundness: CGFloat = AppRoundness.pill
    /// 額度進度條高度
    static let quotaBarHeight: CGFloat = 2
    /// 額度進度條軌道(底層)透明度
    static let quotaBarTrackOpacity: Double = 0.15

    // MARK: - Timing

    /// 套用閱讀偏好後等待 navigator 重排的緩衝
    static let applyPreferencesSettleDelay: TimeInterval = 0.8
    /// 生字標記去抖動視窗
    static let markVocabDebounceDuration: TimeInterval = 0.8
    /// 首次標記完成後底線消退前的停留
    static let firstHighlightFadeOutDelay: TimeInterval = 0.4
    /// 閱讀進度節流寫入延遲
    static let progressFlushDelay: TimeInterval = 1.2
    /// iCloud 檔案就緒等待逾時
    static let iCloudWaitTimeout: TimeInterval = 120
    static let iCloudCurrentPollInterval: TimeInterval = 0.2
    static let iCloudWaitPollInterval: TimeInterval = 0.5

    // MARK: - Translation explanation

    /// 翻譯解釋文字行距（放鬆呼吸感，對齊 Apple Books 段落質感）
    static let translationExplanationLineSpacing: CGFloat = 7

    /// 「語境解釋」section header 與正文之間的縱向間距
    static let translationExplanationHeaderGap: CGFloat = 8

    /// 語境解釋正文段落上方額外內距（與翻譯 / divider 拉開呼吸感）
    static let translationExplanationContentTopInset: CGFloat = 4

    /// 翻譯面板背後 scrim 透明度
    static let translationPanelScrimOpacity: Double = 0.12

    /// 一次移除超過此字數則改走全量重標而非增量
    static let bulkRemovalRemarkThreshold: Int = 10
}
