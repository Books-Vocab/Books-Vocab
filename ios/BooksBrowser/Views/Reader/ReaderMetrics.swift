//
//  ReaderMetrics.swift
//  BooksBrowser
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

    static let settingsSectionSpacing: CGFloat = 18
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
    static let settingsOptionHorizontalPadding: CGFloat = 12
    static let settingsOptionVerticalPadding: CGFloat = 12

    // MARK: - Settings highlight preview / minHeight

    static let settingsHighlightPreviewTrailingInset: CGFloat = 22
    static let settingsModeMinHeight: CGFloat = 112
    static let settingsHighlightMinHeight: CGFloat = 78

    // MARK: - Settings divider

    /// 設定面板分隔線透明度
    static let settingsDividerOpacity: Double = 0.6
}
