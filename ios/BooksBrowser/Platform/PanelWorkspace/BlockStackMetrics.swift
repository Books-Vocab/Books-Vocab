//
//  BlockStackMetrics.swift
//  BooksBrowser
//
//  欄內垂直 block 堆疊的高度約束 — 鏡射 MacDetailPanelMetrics 但 height 語意。
//

import CoreGraphics

enum BlockStackMetrics {
    static let minHeight: CGFloat = 160
    static let defaultHeight: CGFloat = 320
    static let maxHeight: CGFloat = 600        // 垂直 divider clamp 上界
    static let topMinHeight: CGFloat = 120     // 上方 block 至少保留（Phase 4 動態 bound 用）
    static let hitAreaHeight: CGFloat = 8      // 鏡射 MacDetailPanelMetrics.hitAreaWidth
}
