import SwiftUI

/// 設定功能專用版面參數（帳戶區塊、複習區塊）。
enum AppSettingsMetrics {
    static let accountHeroSpacing: CGFloat = 10
    static let accountActionSpacing: CGFloat = 10
    static let accountButtonSpacing: CGFloat = 12
    static let accountRowSpacing: CGFloat = 14
    static let accountAvatarSize: CGFloat = 46
    static let socialBadgeSize: CGFloat = 22

    // 複習節奏那三個 review* 常數（模式塊間距 / stepper 間距 / 數值欄寬）
    // 隨 APP-20260808-240a94 退場：那一頁改用原生 Picker + Stepper，列的幾何由平台決定。

    // MARK: - SettingsSelectionTile（settings + reader 合併後的唯一選擇塊）

    /// 合併前兩份實作真正的差異就是 padding 的責任歸屬：settings 版內建、
    /// reader 版丟給呼叫端。合併版一律由元件內建，只開放兩個具名密度。
    static let selectionTileHorizontalPadding: CGFloat = 14
    /// **具名承認**：合併前的 settings 版把 `controlHorizontalPadding`(14) 當垂直值用
    /// （`controlVerticalPadding` 是 12，存在但沒被用）。那是既有的 token 誤用而不是
    /// 筆誤空間，本票要保幾何不變，所以垂直值仍是 14 —— 但改由這個具名常數承接，
    /// 不再拿水平 token 表達垂直距離。
    static let selectionTileVerticalPaddingStandard: CGFloat = 14
    /// reader 側 option / 色票塊原本自己補的 10pt 垂直內距。
    static let selectionTileVerticalPaddingCompact: CGFloat = 10
    /// 未選狀態描邊透明度。合併前兩份不一致（settings 硬編 0.4、reader 走
    /// `ReaderMetrics.settingsDividerOpacity` = 0.6），取 settings 側。
    static let selectionTileUnselectedBorderOpacity: Double = 0.4
}
