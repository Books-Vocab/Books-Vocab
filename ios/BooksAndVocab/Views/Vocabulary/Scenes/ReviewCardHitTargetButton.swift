import SwiftUI

/// 版面佔位等於 label 本身、可點範圍至少 `minimumSide` 見方的按鈕（#2044）。
///
/// 複習卡的「＋」新增連結原本是 `.plain` 圖示按鈕，可點區≈圖示（約 14pt）。直接
/// `.frame(minWidth: 44, minHeight: 44)` 會把連結區撐高、讓卡片高度跳動並改變 solver
/// 量到的 section 高度。這裡把 label 隱藏後當版面佔位，真正的按鈕疊在上面：按鈕
/// （含 accessibility frame）至少 44×44、以佔位為中心向外擴，版面尺寸完全不變。
struct ReviewCardHitTargetButton<Label: View>: View {
    @ObserveInjection private var inject
    var minimumSide: CGFloat = TodayReviewMetrics.addLinkHitTarget
    let action: () -> Void
    let accessibilityIdentifier: String
    var accessibilityLabel: String? = nil
    @ViewBuilder let label: () -> Label

    var body: some View {
        label()
            .hidden()
            .accessibilityHidden(true)
            .overlay {
                Button(action: action) {
                    label()
                        .frame(minWidth: minimumSide, minHeight: minimumSide)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .appPointerHover()
                .modifier(OptionalAccessibilityLabel(label: accessibilityLabel))
                .accessibilityIdentifier(accessibilityIdentifier)
            }
            .enableInjection()
    }
}

private struct OptionalAccessibilityLabel: ViewModifier {
    let label: String?

    @ViewBuilder
    func body(content: Content) -> some View {
        if let label {
            content.accessibilityLabel(label)
        } else {
            content
        }
    }
}
