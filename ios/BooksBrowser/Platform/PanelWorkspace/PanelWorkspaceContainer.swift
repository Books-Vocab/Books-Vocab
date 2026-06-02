//
//  PanelWorkspaceContainer.swift
//  BooksBrowser
//
//  2D workspace 容器 — regular 渲染 root master + 水平可拖寬欄（Miller columns）；
//  compact 只渲染 root（drill 走既有 NavigationStack push，零改動）。
//
//  INV（D6×D7，根治 413912b3）：ForEach(columns) 以穩定 column.id 為 identity；
//  block 內 NavigationStack（若有）深度恆 0。開新欄只 append 末端、不改既存欄
//  identity/樹位置 → 既存欄不 remount。
//

import SwiftUI

struct PanelWorkspaceContainer<Root: View>: View {
    let workspace: PanelWorkspace
    let layoutMode: LayoutMode
    @ViewBuilder var root: () -> Root

    @State private var liveDrag: (id: ColumnID, value: CGFloat)?

    var body: some View {
        if layoutMode.usesInlineDetail {
            ScrollViewReader { proxy in
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 0) {
                        root()
                            .frame(minWidth: MacDetailPanelMetrics.leftMinWidth)

                        ForEach(workspace.columns) { column in
                            ResizableDivider(
                                axis: .horizontal,
                                currentLength: column.width,
                                bounds: MacDetailPanelMetrics.minWidth...MacDetailPanelMetrics.maxWidth,
                                onDrag: { liveDrag = (column.id, $0) },
                                onCommit: { workspace.setWidth($0, for: column.id); liveDrag = nil },
                                onDoubleClick: { workspace.setWidth(MacDetailPanelMetrics.defaultWidth, for: column.id) }
                            )
                            VerticalBlockStack(workspace: workspace, column: column)
                                .frame(width: liveDrag?.id == column.id ? liveDrag!.value : column.width)
                                .id(column.id)
                                .transition(.drawerReveal)
                        }
                    }
                    .animation(AppMotion.panelState, value: workspace.columns)
                }
                .onChange(of: workspace.columns.last?.id) { _, last in
                    if let last {
                        withAnimation(AppMotion.panelState) { proxy.scrollTo(last, anchor: .trailing) }
                    }
                }
            }
        } else {
            root()
        }
    }
}
