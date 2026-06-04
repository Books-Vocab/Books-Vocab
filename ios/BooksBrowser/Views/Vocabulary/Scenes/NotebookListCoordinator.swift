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
        coverPattern: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async
    func updateNotebook(
        _ notebook: Notebook,
        name: String,
        color: String?,
        coverPattern: String?,
        stagedCoverImagePath: String?,
        originalCoverImagePath: String?,
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
    var exportURL: URL?

    /// reconcile 失敗訊息；nil = 未失敗或已恢復。
    /// View 透過此值顯示 inline error banner + retry CTA。fetch 成功一律清空，
    /// 避免殘留 stale error。
    var reconcileError: String?

    /// 首次 reconcile 是否已完成（成功 / 失敗 / 未登入 early-return 都算）。
    /// 用於區分「載入中」vs「真的沒有單字本」— 鏡像 PR #603 Podcast 修法。
    /// 首次完成後永不重設，後續 refresh 不會再回退顯示 loading placeholder。
    var hasLoadedOnce: Bool = false

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
        // Clear any prior error up front so a stale banner never survives a new
        // reconcile attempt regardless of which branch returns below (mirrors
        // BookshelfCoordinator.clearError at the start of an import batch). The
        // failure branches below re-set it when this attempt also fails.
        reconcileError = nil
        guard authManager.isLoggedIn else {
            // 未登入也算「首次載入流程已完成」— 否則 logged-out users 會永久卡 loading placeholder。
            hasLoadedOnce = true
            return
        }
        defer { hasLoadedOnce = true }

        let remoteNotebooks: [KGNotebook]
        do {
            remoteNotebooks = try await kgService.fetchNotebooks()
        } catch {
            AppLog.kg.error("fetchNotebooks failed: \(error.localizedDescription)")
            if currentNotebooks.isEmpty {
                let nb = Notebook(remoteId: "local-\(UUID().uuidString)", name: "我的單字本", isDefault: true)
                nb.syncStatus = 0
                modelContext.insert(nb)
                modelContext.safeSave()
            }
            // 本地已有 notebook 時 fetch 失敗仍要 inline error 提示，讓使用者
            // 知道清單可能不是最新且可手動重試。空清單情境上面已 fallback 本地預設。
            if !currentNotebooks.isEmpty {
                reconcileError = error.localizedDescription
            }
            return
        }

        // 查全量（含 isDeleted）避免已刪除 notebook 無法被 reconcile 修正
        let allLocal: [Notebook]
        do {
            allLocal = try modelContext.fetch(FetchDescriptor<Notebook>())
        } catch {
            AppLog.kg.error("fetch all notebooks failed: \(error.localizedDescription)")
            reconcileError = error.localizedDescription
            return
        }

        let localByRemoteId = Dictionary(
            allLocal.map { ($0.remoteId, $0) },
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
                local.coverPattern = remote.coverPattern
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
                nb.coverPattern = remote.coverPattern
                nb.sortOrder = remote.sortOrder
                nb.syncStatus = 1
                modelContext.insert(nb)
            }
        }

        for local in allLocal where local.syncStatus == 1 && !remoteIds.contains(local.remoteId) && !local.isDeleted {
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
            // 若全域 active notebook 指向剛被刪掉的 notebook（典型場景：跨裝置刪除），
            // 必須清掉 UserDefaults，否則 `Book.resolvedNotebookId` 還會 fall through
            // 到死 id，造成新建 entry 變孤兒。
            let activeKey = "activeNotebookId"
            if let active = UserDefaults.standard.string(forKey: activeKey),
               newlyDeleted.contains(active) {
                UserDefaults.standard.removeObject(forKey: activeKey)
                AppLog.kg.warning("cleared stale activeNotebookId after remote delete: \(active)")
            }
        }

        modelContext.safeSave()
        reconcileError = nil
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
        coverPattern: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async {
        do {
            let remote = try await kgService.createNotebook(name: name, color: color, coverPattern: coverPattern)
            let nb = Notebook(remoteId: remote.id, name: remote.name, color: remote.color)
            nb.coverPattern = remote.coverPattern
            nb.syncStatus = 1
            modelContext.insert(nb)
            if modelContext.safeSaveWithToast(toastCoordinator) {
                toastCoordinator.success("已建立".localized)
            }
        } catch {
            toastCoordinator.error("建立失敗".localized)
            AppLog.kg.error("createNotebook failed: \(error.localizedDescription)")
        }
    }

    func updateNotebook(
        _ notebook: Notebook,
        name: String,
        color: String?,
        coverPattern: String?,
        stagedCoverImagePath: String?,
        originalCoverImagePath: String?,
        modelContext: ModelContext,
        kgService: any KGServing,
        toastCoordinator: AppToastCoordinator
    ) async {
        do {
            let remote = try await kgService.updateNotebook(id: notebook.remoteId, name: name, color: color, coverPattern: coverPattern)
            notebook.name = remote.name
            notebook.color = remote.color
            notebook.coverPattern = remote.coverPattern
            // 封面圖是 device-local（不上 server / 不參與 reconcile）。只有 API 成功後
            // 才落地新封面 + 刪舊圖 → 與 server 欄位的成敗一致（track-23，全有或全無）。
            let coverPlan = NotebookCoverCommit.plan(staged: stagedCoverImagePath, original: originalCoverImagePath)
            notebook.coverImagePath = coverPlan.resolvedPath
            notebook.updatedAt = Date()
            if modelContext.safeSaveWithToast(toastCoordinator) {
                NotebookCoverCommit.removeStaleFile(coverPlan)
                toastCoordinator.success("已更新".localized)
            }
        } catch {
            // API 失敗：不動 coverImagePath、不刪舊圖；staged 新圖由 sheet 取消流程或
            // 下次編輯處理。server 欄位與本地封面同時維持舊值，無 drift。
            toastCoordinator.error("更新失敗".localized)
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

            // Hard guarantee mirror of the reconcile-path UserDefaults cleanup:
            // even if `setActiveNotebook` was a no-op (caller injection 不保證寫入)
            // 或 `resolveFallbackNotebookId` 回傳 nil（only-notebook edge case），
            // 直接清掉指向 deletedId 的 stale activeNotebookId，避免 Book.resolvedNotebookId
            // 之後 fall through 到死 id。
            if UserDefaults.standard.string(forKey: "activeNotebookId") == deletedId {
                UserDefaults.standard.removeObject(forKey: "activeNotebookId")
            }

            if modelContext.safeSaveWithToast(toastCoordinator) {
                toastCoordinator.success("已刪除".localized)
            }
        } catch {
            toastCoordinator.error("刪除失敗".localized)
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
