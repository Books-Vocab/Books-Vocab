//
//  PanelKind.swift
//  BooksBrowser
//
//  2D 可堆疊 block workspace 的 payload 型別。
//

import Foundation

/// 每個 block 承載的 payload。**value-pure**（Equatable/Hashable，無 @Model 物件）
/// → 供 SwiftUI 穩定 diff + coordinator 單元測試。live model 物件由 `PanelHost`
/// resolver 經 id 反查，payload 只帶可重建的 id 快照。
///
/// 擴展點：加一個 case 即加一種 block 類型，引擎（`PanelWorkspace` / container）零改動。
enum PanelKind: Equatable, Hashable {
    case podcastSeries(remoteID: String)     // 經 service 反查（非 SwiftData）
    case podcastEpisode(remoteID: String)
    case wordDetail(entryID: UUID)           // VocabularyEntry.id: UUID
    case reviewSession(entryIDs: [UUID])     // entry-id 快照 → resolver 重建 TodayReviewSession
    case linkedWord(entryID: UUID)           // 垂直軸用例
}

/// Block 穩定身分 — 供 SwiftUI `ForEach` identity 與精準 close。
struct BlockID: Hashable { let raw = UUID() }

/// Column 穩定身分。
struct ColumnID: Hashable { let raw = UUID() }
