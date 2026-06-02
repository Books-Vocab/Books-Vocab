//
//  PanelModels.swift
//  BooksBrowser
//
//  2D workspace 的值型別：垂直 block 與水平 column。
//

import CoreGraphics

/// 垂直堆疊中的單一 block。
struct Block: Identifiable, Equatable {
    let id = BlockID()
    let kind: PanelKind
    var height: CGFloat? = nil          // nil = flexible 均分

    init(kind: PanelKind, height: CGFloat? = nil) {
        self.kind = kind
        self.height = height
    }
}

/// 一欄 = 一個垂直 block stack + 欄寬。
struct WorkColumn: Identifiable, Equatable {
    let id = ColumnID()
    var blocks: [Block]
    var width: CGFloat = MacDetailPanelMetrics.defaultWidth

    init(blocks: [Block]) { self.blocks = blocks }
    init(kind: PanelKind) { self.blocks = [Block(kind: kind)] }
}
