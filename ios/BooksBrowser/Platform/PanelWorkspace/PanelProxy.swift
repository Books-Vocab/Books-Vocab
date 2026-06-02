//
//  PanelProxy.swift
//  BooksBrowser
//
//  block 內容觸發導航 / 自關的握把 — 知道自身 (column, block)。
//

import SwiftUI

@MainActor
struct PanelProxy {
    let columnID: ColumnID
    let blockID: BlockID
    private let workspace: PanelWorkspace

    init(columnID: ColumnID, blockID: BlockID, workspace: PanelWorkspace) {
        self.columnID = columnID
        self.blockID = blockID
        self.workspace = workspace
    }

    /// 在自身欄之後開新欄（水平 drill，Miller 截斷右側）。
    func openChildColumn(_ kind: PanelKind) {
        workspace.openColumn(kind, after: columnID)
    }

    /// 在自身欄內垂直疊一個 block（split / reference）。
    func stackHere(_ kind: PanelKind) {
        _ = workspace.stack(kind, in: columnID)
    }

    /// 關閉自身 block（欄空則連帶收欄 + 串聯右側）。
    func closeSelf() {
        workspace.closeBlock(blockID)
    }
}
