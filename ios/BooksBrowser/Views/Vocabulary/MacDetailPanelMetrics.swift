import SwiftUI

/// macOS 雙欄詳情面板的寬度約束與分隔線視覺參數。
enum MacDetailPanelMetrics {
    static let defaultWidth: CGFloat = 420
    static let minWidth: CGFloat = 280
    static let maxWidth: CGFloat = 600
    static let leftMinWidth: CGFloat = 300
    static let hitAreaWidth: CGFloat = 8
    /// 分隔線靜止時的視覺透明度
    static let dividerIdleOpacity: Double = 0.2
    /// 分隔線拖曳中的視覺透明度（加亮回饋）
    static let dividerActiveOpacity: Double = 0.5
}
