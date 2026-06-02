//
//  VerticalBlockStack.swift
//  BooksBrowser
//
//  一欄內的垂直 block 堆疊 + 欄內可拖高 divider。
//  liveDrag 為 transient（一次只一條 divider 拖曳）；放開由 onCommit 寫回 coordinator。
//

import SwiftUI

struct VerticalBlockStack: View {
    let workspace: PanelWorkspace
    let column: WorkColumn

    @State private var liveDrag: (id: BlockID, value: CGFloat)?

    var body: some View {
        VStack(spacing: 0) {
            ForEach(Array(column.blocks.enumerated()), id: \.element.id) { idx, block in
                if idx > 0 {
                    ResizableDivider(
                        axis: .vertical,
                        currentLength: block.height ?? BlockStackMetrics.defaultHeight,
                        bounds: BlockStackMetrics.minHeight...BlockStackMetrics.maxHeight,
                        onDrag: { liveDrag = (block.id, $0) },
                        onCommit: { workspace.setHeight($0, for: block.id); liveDrag = nil }
                    )
                }
                BlockChrome(onClose: { workspace.closeBlock(block.id) }) {
                    PanelHost(
                        kind: block.kind,
                        proxy: PanelProxy(columnID: column.id, blockID: block.id, workspace: workspace)
                    )
                }
                .frame(maxHeight: liveDrag?.id == block.id ? liveDrag!.value : (block.height ?? .infinity))
                .transition(.statusRowReveal)
            }
        }
        .animation(AppMotion.panelState, value: column.blocks)
    }
}
