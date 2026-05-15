import SwiftUI

/// 跨平台可拖曳分隔線 — macOS/iPad regular size class 共用。
/// 8pt 透明 hit area，中間 1pt 視覺線，拖曳時加亮。
///
/// 寬度 state 由 parent 持有：
/// - `panelWidth`: 持久化寬度（@AppStorage），僅 onEnded 寫入
/// - `dragWidth`: 拖曳中即時寬度，nil = 未拖曳
struct DraggableDivider: View {
    @Binding var panelWidth: CGFloat
    @Binding var dragWidth: CGFloat?
    let containerWidth: CGFloat
    var onDoubleClick: () -> Void = {}

    @State private var dragStartWidth: CGFloat = 0
    @GestureState private var isActiveDrag = false

    @Environment(\.appTheme) private var theme

    private var effectiveMax: CGFloat {
        let max = containerWidth - AppMetrics.MacDetailPanel.leftMinWidth
        return min(AppMetrics.MacDetailPanel.maxWidth, Swift.max(max, AppMetrics.MacDetailPanel.minWidth))
    }

    var body: some View {
        Rectangle()
            .fill(isActiveDrag
                ? theme.palette.divider.opacity(AppMetrics.MacDetailPanel.dividerActiveOpacity)
                : Color.clear)
            .frame(width: AppMetrics.MacDetailPanel.hitAreaWidth)
            .contentShape(Rectangle())
            .overlay(alignment: .center) {
                Rectangle()
                    .fill(theme.palette.divider.opacity(
                        isActiveDrag
                            ? AppMetrics.MacDetailPanel.dividerActiveOpacity
                            : AppMetrics.MacDetailPanel.dividerIdleOpacity
                    ))
                    .frame(width: 1)
            }
            #if os(macOS)
            .modifier(CursorModifier())
            #endif
            .highPriorityGesture(dragGesture)
            .onChange(of: isActiveDrag) { _, active in
                if !active && dragWidth != nil {
                    panelWidth = dragWidth!
                    dragWidth = nil
                }
            }
            #if os(macOS)
            .onTapGesture(count: 2) { onDoubleClick() }
            #endif
    }

    private var dragGesture: some Gesture {
        DragGesture(minimumDistance: 3, coordinateSpace: .global)
            .updating($isActiveDrag) { _, state, _ in
                state = true
            }
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
    }
}

// MARK: - macOS Cursor

#if os(macOS)
import AppKit

private struct CursorModifier: ViewModifier {
    @State private var isHovering = false

    func body(content: Content) -> some View {
        content
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
    }
}
#endif

// MARK: - Helpers

private extension CGFloat {
    func clamped(to range: ClosedRange<CGFloat>) -> CGFloat {
        Swift.min(Swift.max(self, range.lowerBound), range.upperBound)
    }
}
