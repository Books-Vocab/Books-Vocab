//
//  NotebookReconciler.swift
//  Books & Vocab
//
//  Notebook reconcile 的純邏輯核心（無網路 / 無 UserDefaults / 不 save）。
//  從 `NotebookListCoordinator.reconcileNotebooks` 抽出，使 upsert / tombstone /
//  孤兒回收 / 離線占位 等不變式可單元測試 — 對齊 `PodcastSyncService.reconcileLocalState`
//  範式。Server 為權威；本地 SwiftData 為鏡像。

import Foundation
import SwiftData

enum NotebookReconciler {

    /// 將 server 權威 notebook 清單與本地 SwiftData reconcile。
    ///
    /// - upsert：remote 新增 → insert；remoteId 命中 → 更新欄位（含 `isSoftDeleted`，對應遠端刪除）
    /// - tombstone：本地 `syncStatus == 1` 但 remote 不回報 → 標記 `isSoftDeleted`（其他裝置刪除）
    /// - **reap 孤兒**：本地 `remoteId` 前綴 `local-` 且 `syncStatus == 0` 的離線占位本，
    ///   在「已有可用真本」時硬刪。修舊版 offline fallback 用隨機 `local-<UUID>` 製造、
    ///   且永遠不被上面 `syncStatus == 1` tombstone pass 回收的重複「我的單字本」幽靈本。
    ///   殘留 entry 改派 `"default"`（對齊 `VocabularyEntry.resolveNotebookId` sentinel），
    ///   **不** queueDelete（那些卡屬於 server 上的真本，不可刪）。
    /// - cascade：被 tombstone 的**真本**下 entries `queueDelete`（讓 server 也刪）。
    ///
    /// - Returns: 本回合轉為不可見的 remoteId 集合（tombstoned ∪ reaped），
    ///   供 caller 清掉指向它們的 stale `activeNotebookId`。
    /// - Note: **不**呼叫 `modelContext.save()`；由 caller 統一 save。
    @discardableResult
    static func reconcile(
        remote: [KGNotebook],
        local: [Notebook],
        allEntries: [VocabularyEntry],
        modelContext: ModelContext
    ) -> Set<String> {
        let localByRemoteId = Dictionary(
            local.map { ($0.remoteId, $0) },
            uniquingKeysWith: { first, _ in first }
        )
        let remoteIds = Set(remote.map(\.id))
        var tombstoned: Set<String> = []

        // Upsert remote → local
        for r in remote {
            if let l = localByRemoteId[r.id] {
                let wasAlive = !l.isSoftDeleted
                l.name = r.name
                l.color = r.color
                l.coverPattern = r.coverPattern
                l.isDefault = r.isDefault
                l.sortOrder = r.sortOrder
                l.isSoftDeleted = r.isDeleted
                l.syncStatus = 1
                if wasAlive && r.isDeleted { tombstoned.insert(l.remoteId) }
            } else if !r.isDeleted {
                let nb = Notebook(
                    remoteId: r.id,
                    name: r.name,
                    color: r.color,
                    isDefault: r.isDefault
                )
                nb.coverPattern = r.coverPattern
                nb.sortOrder = r.sortOrder
                nb.syncStatus = 1
                modelContext.insert(nb)
            }
        }

        // 曾同步但 server 不再回報 → tombstone（跨裝置刪除）
        for l in local where l.syncStatus == 1 && !remoteIds.contains(l.remoteId) && !l.isSoftDeleted {
            l.isSoftDeleted = true
            l.updatedAt = Date()
            tombstoned.insert(l.remoteId)
        }

        // Reap 遺留 local-* 孤兒（僅在已有可用真本時，否則離線只有孤兒當預設會被清光）
        var reaped: Set<String> = []
        let hasUsableReal = local.contains { !$0.remoteId.hasPrefix("local-") && !$0.isSoftDeleted }
            || remote.contains { !$0.isDeleted }
        if hasUsableReal {
            for orphan in local
            where orphan.remoteId.hasPrefix("local-") && orphan.syncStatus == 0 && !orphan.isSoftDeleted {
                for entry in allEntries where entry.notebookId == orphan.remoteId {
                    entry.notebookId = "default"
                }
                reaped.insert(orphan.remoteId)
                modelContext.delete(orphan)
            }
        }

        // Cascade：僅 tombstone 的真本（reaped 孤兒的 entry 已改派、不刪卡）
        if !tombstoned.isEmpty {
            cascadeDeleteEntries(matching: tombstoned, allEntries: allEntries, modelContext: modelContext)
        }

        return tombstoned.union(reaped)
    }

    /// 離線 / `fetchNotebooks` 失敗且本地無可見本子時，建立 canonical default 占位本。
    ///
    /// 用 `remoteId == "default"`（server-side sentinel）而非隨機 `local-<UUID>`，使真本
    /// 同步進來時 `reconcile` 的 upsert 就地合併、**不再分裂出孤兒**。idempotent：
    /// 已存在 `"default"` 紀錄則不重建（被刪的 sentinel 直接 resurrect，對齊
    /// `resolveNotebookId` 對 `"default"` 永遠有效的契約）。
    static func ensureOfflineDefault(local: [Notebook], modelContext: ModelContext) {
        if let existing = local.first(where: { $0.remoteId == "default" }) {
            if existing.isSoftDeleted {
                existing.isSoftDeleted = false
                existing.updatedAt = Date()
            }
            return
        }
        guard !local.contains(where: { !$0.isSoftDeleted }) else { return }
        let nb = Notebook(remoteId: "default", name: "我的單字本", isDefault: true)
        nb.syncStatus = 0
        modelContext.insert(nb)
    }

    /// 將指定 notebook 集合下尚未刪除的 entries 排入刪除 queue。
    /// 一律走 `queueDelete()`，由 sync 層處理 lifecycle，避免 hard delete 與
    /// in-flight upload task 競爭。
    static func cascadeDeleteEntries(
        matching notebookIds: Set<String>,
        allEntries: [VocabularyEntry],
        modelContext: ModelContext
    ) {
        for entry in allEntries where notebookIds.contains(entry.notebookId) && entry.syncAction != .delete {
            entry.queueDelete()
        }
    }
}
