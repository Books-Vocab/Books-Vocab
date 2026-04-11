//
//  NotebookListCoordinator.swift
//  BooksBrowser
//
//  單字本列表的 DB + API 操作封裝

import Foundation
import SwiftData

@MainActor protocol NotebookListCoordinating: AnyObject, Observable {
    func reconcileNotebooks(
        authManager: any AuthManaging,
        currentNotebooks: [Notebook],
        allEntries: [VocabularyEntry],
        modelContext: ModelContext,
        kgService: any KGServing
    ) async
    func createNotebook(
        name: String,
        color: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async
    func updateNotebook(
        _ notebook: Notebook,
        name: String,
        color: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async
    func deleteNotebook(
        _ notebook: Notebook,
        isActive: Bool,
        availableNotebooks: [Notebook],
        allEntries: [VocabularyEntry],
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator,
        setActiveNotebook: (String) -> Void
    ) async
}

@Observable @MainActor
final class NotebookListCoordinator: NotebookListCoordinating {

    /// 從 server 拉 notebook 清單並與本地 reconcile：
    /// - remote 新增 → 本地 insert
    /// - remote 同名 remoteId → 更新欄位（含 isDeleted，對應遠端刪除）
    /// - 本地存在但 remote 不回報 → 本地標記 isDeleted（對應被其他裝置刪除）
    /// - 任何轉為 isDeleted 的 notebook 都 cascade 其 entries
    ///
    /// 與舊版 `ensureDefaultNotebook` 不同：**每次呼叫都 reconcile**，不再只在 `currentNotebooks.isEmpty` 時跑。
    func reconcileNotebooks(
        authManager: any AuthManaging,
        currentNotebooks: [Notebook],
        allEntries: [VocabularyEntry],
        modelContext: ModelContext,
        kgService: any KGServing
    ) async {
        guard authManager.isLoggedIn else { return }

        let remoteNotebooks: [KGNotebook]
        do {
            remoteNotebooks = try await kgService.fetchNotebooks()
        } catch {
            AppLog.kg.error("fetchNotebooks failed: \(error.localizedDescription)")
            // 離線且本地完全沒 notebook → 建一本 pending fallback 讓 UI 有內容
            // 用 UUID 避免與 server 真正 default 的 remoteId 撞
            if currentNotebooks.isEmpty {
                let nb = Notebook(remoteId: "local-\(UUID().uuidString)", name: "我的單字本", isDefault: true)
                nb.syncStatus = 0
                modelContext.insert(nb)
                modelContext.safeSave()
            }
            return
        }

        // 防禦重複 remoteId（若資料已損壞，保留第一個遇到的 entry）
        let localByRemoteId = Dictionary(
            currentNotebooks.map { ($0.remoteId, $0) },
            uniquingKeysWith: { first, _ in first }
        )
        let remoteIds = Set(remoteNotebooks.map(\.id))
        var newlyDeleted: Set<String> = []

        // Upsert remote → local
        for remote in remoteNotebooks {
            if let local = localByRemoteId[remote.id] {
                let wasAlive = !local.isDeleted
                local.name = remote.name
                local.color = remote.color
                local.isDefault = remote.isDefault
                local.sortOrder = remote.sortOrder
                local.isDeleted = remote.isDeleted
                local.syncStatus = 1
                if wasAlive && remote.isDeleted {
                    newlyDeleted.insert(local.remoteId)
                }
            } else if !remote.isDeleted {
                let nb = Notebook(
                    remoteId: remote.id,
                    name: remote.name,
                    color: remote.color,
                    isDefault: remote.isDefault
                )
                nb.sortOrder = remote.sortOrder
                nb.syncStatus = 1
                modelContext.insert(nb)
            }
        }

        // Local synced 但 remote 沒回報 → 標記 isDeleted（保留 syncStatus=0 的 pending 本地 notebook）
        for local in currentNotebooks where local.syncStatus == 1 && !remoteIds.contains(local.remoteId) && !local.isDeleted {
            local.isDeleted = true
            local.updatedAt = Date()
            newlyDeleted.insert(local.remoteId)
        }

        // Cascade：剛被標為 isDeleted 的 notebook 下的 entries 也要跟著 queueDelete
        if !newlyDeleted.isEmpty {
            Self.cascadeDeleteEntries(
                matching: newlyDeleted,
                allEntries: allEntries,
                modelContext: modelContext
            )
        }

        modelContext.safeSave()
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

    func createNotebook(
        name: String,
        color: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async {
        do {
            let remote = try await kgService.createNotebook(name: name, color: color)
            let nb = Notebook(remoteId: remote.id, name: remote.name, color: remote.color)
            nb.syncStatus = 1
            modelContext.insert(nb)
            if modelContext.safeSaveWithToast(toastCoordinator) {
                toastCoordinator.success("已建立")
            }
        } catch {
            toastCoordinator.error("建立失敗")
            AppLog.kg.error("createNotebook failed: \(error.localizedDescription)")
        }
    }

    func updateNotebook(
        _ notebook: Notebook,
        name: String,
        color: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async {
        do {
            let remote = try await kgService.updateNotebook(id: notebook.remoteId, name: name, color: color)
            notebook.name = remote.name
            notebook.color = remote.color
            notebook.updatedAt = Date()
            if modelContext.safeSaveWithToast(toastCoordinator) {
                toastCoordinator.success("已更新")
            }
        } catch {
            toastCoordinator.error("更新失敗")
            AppLog.kg.error("updateNotebook failed: \(error.localizedDescription)")
        }
    }

    func deleteNotebook(
        _ notebook: Notebook,
        isActive: Bool,
        availableNotebooks: [Notebook],
        allEntries: [VocabularyEntry],
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator,
        setActiveNotebook: (String) -> Void
    ) async {
        let deletedId = notebook.remoteId
        do {
            try await kgService.deleteNotebook(id: deletedId)

            Self.cascadeDeleteEntries(
                matching: [deletedId],
                allEntries: allEntries,
                modelContext: modelContext
            )

            if isActive, let fallback = Self.resolveFallbackNotebookId(
                excluding: deletedId,
                from: availableNotebooks
            ) {
                setActiveNotebook(fallback)
            }
            notebook.isDeleted = true
            notebook.updatedAt = Date()
            if modelContext.safeSaveWithToast(toastCoordinator) {
                toastCoordinator.success("已刪除")
            }
        } catch {
            toastCoordinator.error("刪除失敗")
            AppLog.kg.error("deleteNotebook failed: \(error.localizedDescription)")
        }
    }

    /// 選擇 active notebook 的 fallback：isDefault 優先 → 第一個非刪除非自己 → nil（caller 應保留舊值）。
    static func resolveFallbackNotebookId(
        excluding deletedId: String,
        from notebooks: [Notebook]
    ) -> String? {
        let candidates = notebooks.filter { !$0.isDeleted && $0.remoteId != deletedId }
        if let def = candidates.first(where: { $0.isDefault }) {
            return def.remoteId
        }
        return candidates.first?.remoteId
    }
}
