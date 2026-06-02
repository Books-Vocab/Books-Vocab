//
//  ResizableDivider.swift
//  BooksBrowser
//
//  axis-generic 可拖拉分隔線（重寫自 DraggableDivider）。
//  callback-based:不持有尺寸 state（coordinator 為 SoT）。parent 用 onDrag 更新
//  即時 transient、onCommit 寫回 coordinator。無 .constant(nil) hack。
//

import SwiftUI

struct ResizableDivider: View {
    let axis: Axis                       // .horizontal → 調寬；.vertical → 調高
    let currentLength: CGFloat           // 已 commit 的尺寸（唯讀，作 drag 起點）
    let bounds: ClosedRange<CGFloat>
    let onDrag: (CGFloat) -> Void        // 拖曳中即時值 → parent 更新 transient
    let onCommit: (CGFloat) -> Void      // 放開最終值 → coordinator setWidth/setHeight
    var onDoubleClick: () -> Void = {}

    @Environment(\.appTheme) private var theme
    @GestureState private var isActiveDrag = false
    @State private var dragStart: CGFloat = 0

    static func clamp(_ v: CGFloat, to r: ClosedRange<CGFloat>) -> CGFloat {
        Swift.min(Swift.max(v, r.lowerBound), r.upperBound)
    }

    var body: some View {
        Rectangle()
            .fill(isActiveDrag
                  ? theme.palette.divider.opacity(MacDetailPanelMetrics.dividerActiveOpacity)
                  : Color.clear)
            .frame(width: axis == .horizontal ? MacDetailPanelMetrics.hitAreaWidth : nil,
                   height: axis == .vertical ? BlockStackMetrics.hitAreaHeight : nil)
            .contentShape(Rectangle())
            .overlay(alignment: .center) {
                Rectangle()
                    .fill(theme.palette.divider.opacity(
                        isActiveDrag
                            ? MacDetailPanelMetrics.dividerActiveOpacity
                            : MacDetailPanelMetrics.dividerIdleOpacity
                    ))
                    .frame(width: axis == .horizontal ? 1 : nil,
                           height: axis == .vertical ? 1 : nil)
            }
            .highPriorityGesture(drag)
            #if targetEnvironment(macCatalyst)
            .onTapGesture(count: 2) { onDoubleClick() }
            .overlay { MacColumnResizeCursor(axis: axis) }
            #endif
    }

    private func length(from translation: CGSize) -> CGFloat {
        // 水平：欄在右,往左拖變寬 → 減 translation.width（鏡射舊 divider）。
        // 垂直：block 在下,往上拖變高 → 減 translation.height。
        let delta = axis == .horizontal ? translation.width : translation.height
        return Self.clamp(dragStart - delta, to: bounds)
    }

    private var drag: some Gesture {
        DragGesture(minimumDistance: 3, coordinateSpace: .global)
            .updating($isActiveDrag) { _, state, _ in state = true }
            .onChanged { value in
                if !isActiveDrag { dragStart = currentLength }   // 首幀記起點
                onDrag(length(from: value.translation))
            }
            .onEnded { value in onCommit(length(from: value.translation)) }
    }
}
