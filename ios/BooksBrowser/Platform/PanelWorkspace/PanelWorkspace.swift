//
//  PanelWorkspace.swift
//  BooksBrowser
//
//  2D 可堆疊 block workspace 的堆疊模式管理 — 唯一 SoT。
//

import SwiftUI

/// 管理水平 column stack（Miller 截斷）+ 每欄垂直 block stack。
///
/// 不變式：
/// - 無空欄（`closeBlock` 移除最後一個 block 時連帶收欄）。
/// - `columns` 順序即視覺左→右。
/// - 關欄串聯關其右側（子欄是父欄選取衍生，孤兒欄無意義）。
@Observable @MainActor
final class PanelWorkspace {
    private(set) var columns: [WorkColumn] = []

    // MARK: - 水平軸（navigate / drill，Miller 截斷語意）

    /// 在 `after` 欄之後開新欄並截斷其右側；`after == nil` 視為 root → 截斷全部。
    @discardableResult
    func openColumn(_ kind: PanelKind, after columnID: ColumnID?) -> ColumnID {
        let keep: Int
        if let columnID, let idx = columns.firstIndex(where: { $0.id == columnID }) {
            keep = idx + 1
        } else {
            keep = 0
        }
        columns = Array(columns.prefix(keep))
        let col = WorkColumn(kind: kind)
        columns.append(col)
        return col.id
    }

    /// 關閉該欄及其右側全部。
    func closeColumn(_ id: ColumnID) {
        guard let idx = columns.firstIndex(where: { $0.id == id }) else { return }
        columns = Array(columns.prefix(idx))
    }

    // MARK: - 垂直軸（split / pin / reference）

    @discardableResult
    func stack(_ kind: PanelKind, in columnID: ColumnID) -> BlockID? {
        guard let idx = columns.firstIndex(where: { $0.id == columnID }) else { return nil }
        let block = Block(kind: kind)
        columns[idx].blocks.append(block)
        return block.id
    }

    /// 移除 block；欄空 → 收欄並串聯關右側（維持「無空欄」不變式）。
    func closeBlock(_ id: BlockID) {
        guard let cIdx = columns.firstIndex(where: { $0.blocks.contains(where: { $0.id == id }) }) else { return }
        columns[cIdx].blocks.removeAll { $0.id == id }
        if columns[cIdx].blocks.isEmpty {
            columns = Array(columns.prefix(cIdx))
        }
    }

    // MARK: - 尺寸 mutator（container/divider 的 commit 寫回；coordinator 為 SoT）
    // 兩者皆 by-id 查找（非 index）→ insert/remove 下穩定。由 ResizableDivider onCommit 呼叫。
    // 不能走 @Bindable 雙向綁進 private(set) array（編譯不過）。

    func setWidth(_ width: CGFloat, for columnID: ColumnID) {
        guard let idx = columns.firstIndex(where: { $0.id == columnID }) else { return }
        columns[idx].width = width
    }

    func setHeight(_ height: CGFloat, for blockID: BlockID) {
        guard let cIdx = columns.firstIndex(where: { $0.blocks.contains(where: { $0.id == blockID }) }),
              let bIdx = columns[cIdx].blocks.firstIndex(where: { $0.id == blockID }) else { return }
        columns[cIdx].blocks[bIdx].height = height
    }

    func reset() { columns = [] }
}
