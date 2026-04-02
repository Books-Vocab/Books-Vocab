#if os(macOS)
import SwiftUI
import AppKit

/// macOS 專用可拖曳分隔線。
/// 8pt 透明 hit area，中間 1pt 視覺線，hover 切換 resize 游標。
///
/// 寬度 state 由 parent 持有：
/// - `panelWidth`: 持久化寬度（@AppStorage），僅 onEnded 寫入
/// - `dragWidth`: 拖曳中即時寬度，nil = 未拖曳
struct MacDividerHandle: View {
    @Binding var panelWidth: CGFloat
    @Binding var dragWidth: CGFloat?
    let containerWidth: CGFloat
    var onDoubleClick: () -> Void

    @State private var dragStartWidth: CGFloat = 0
    @State private var isHovering = false

    private var effectiveMax: CGFloat {
        min(
            AppMetrics.MacDetailPanel.maxWidth,
            containerWidth - AppMetrics.MacDetailPanel.leftMinWidth
        )
    }

    var body: some View {
        Rectangle()
            .fill(Color.clear)
            .frame(width: AppMetrics.MacDetailPanel.hitAreaWidth)
            .contentShape(Rectangle())
            .overlay {
                Divider()
            }
            .onHover { hovering in
                isHovering = hovering
                if hovering {
                    NSCursor.resizeLeftRight.push()
                } else {
                    NSCursor.pop()
                }
            }
            .onDisappear {
                if isHovering {
                    NSCursor.pop()
                    isHovering = false
                }
            }
            .gesture(
                DragGesture(minimumDistance: 3, coordinateSpace: .global)
                    .onChanged { value in
                        if dragWidth == nil {
                            dragStartWidth = panelWidth
                        }
                        let newWidth = dragStartWidth - value.translation.width
                        dragWidth = newWidth.clamped(
                            to: AppMetrics.MacDetailPanel.minWidth...effectiveMax
                        )
                    }
                    .onEnded { _ in
                        if let finalWidth = dragWidth {
                            panelWidth = finalWidth
                        }
                        dragWidth = nil
                    }
            )
            .onTapGesture(count: 2) {
                onDoubleClick()
            }
    }
}

private extension CGFloat {
    func clamped(to range: ClosedRange<CGFloat>) -> CGFloat {
        Swift.min(Swift.max(self, range.lowerBound), range.upperBound)
    }
}
#endif
