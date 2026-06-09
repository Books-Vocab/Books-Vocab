//
//  NotebookListCoordinator.swift
//  Books & Vocab
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
    /// - remote 同名 remoteId → 更新欄位（含 isSoftDeleted，對應遠端刪除）
    /// - 本地存在但 remote 不回報 → 本地標記 isSoftDeleted（對應被其他裝置刪除）
    /// - 任何轉為 isSoftDeleted 的 notebook 都 cascade 其 entries
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
            // 離線占位：用 canonical "default" sentinel（非隨機 local-UUID），真本同步進來
            // 時 reconcile upsert 就地合併，不再分裂出永遠回收不掉的幽靈「我的單字本」。
            let allLocal = (try? modelContext.fetch(FetchDescriptor<Notebook>())) ?? []
            NotebookReconciler.ensureOfflineDefault(local: allLocal, modelContext: modelContext)
            modelContext.safeSave()
            // 本地已有 notebook 時 fetch 失敗仍要 inline error 提示，讓使用者
            // 知道清單可能不是最新且可手動重試。空清單情境上面已 fallback 本地預設。
            if !currentNotebooks.isEmpty {
                reconcileError = error.localizedDescription
            }
            return
        }

        // 查全量（含 isSoftDeleted）避免已刪除 notebook 無法被 reconcile 修正
        let allLocal: [Notebook]
        do {
            allLocal = try modelContext.fetch(FetchDescriptor<Notebook>())
        } catch {
            AppLog.kg.error("fetch all notebooks failed: \(error.localizedDescription)")
            reconcileError = error.localizedDescription
            return
        }

        let removed = NotebookReconciler.reconcile(
            remote: remoteNotebooks,
            local: allLocal,
            allEntries: allEntries,
            modelContext: modelContext
        )

        // 若全域 active notebook 指向剛轉不可見的本子（跨裝置刪除 / 孤兒回收），清掉
        // UserDefaults，否則 `Book.resolvedNotebookId` 還會 fall through 到死 id，
        // 造成新建 entry 變孤兒。
        if let active = ActiveNotebookStore.shared.activeNotebookIdIfSet,
           removed.contains(active) {
            ActiveNotebookStore.shared.clearStale()
            AppLog.kg.warning("cleared stale activeNotebookId after reconcile remove: \(active)")
        }

        modelContext.safeSave()
        reconcileError = nil
    }

    /// active notebook backend cold-start：server 值僅在本機從未寫過
    /// （`snapshot.updatedAt == nil`）時套用，避免覆蓋本機已有的跨裝置權威值。
    /// iOS↔iOS 靠 iCloud KVS（store init resolve），此處主要收斂 chrome / web → iOS 方向。
    func coldStartActiveNotebook(authManager: any AuthManaging, kgService: any KGServing) async {
        guard authManager.isLoggedIn else { return }
        guard ActiveNotebookStore.shared.snapshot.updatedAt == nil else { return }
        _ = KGFeatureFlags.serverVocabUiLwwEnabled  // keep wired for future LWW flip
        do {
            let config = try await kgService.fetchUserConfig()
            // 僅在 server 帶真實時戳時套用：updated_at == nil 表示後端從未被任何端
            // push（B1 default fallback），套了也不算數 — 且會讓本地 snapshot.updatedAt
            // 維持 nil，下次 .task 又 re-fire fetchUserConfig（idempotent 但浪費）。
            guard let vu = config.vocab_ui, let ts = vu.updated_at else { return }
            ActiveNotebookStore.shared.applyServerState(
                ActiveNotebookState(activeNotebookId: vu.active_notebook_id, updatedAt: ts)
            )
        } catch {
            AppLog.kg.warning("coldStartActiveNotebook failed: \(error.localizedDescription)")
        }
    }

    /// best-effort push active notebook 到後端（讓 chrome / web 能讀）。失敗不 rollback：
    /// iCloud KVS 已是 Apple 裝置跨裝置權威，backend 為補充橋樑，下次切換 / cold-start 收斂。
    /// `id` 與 `updatedAt` 由 caller 在 setActive 後**同步**一起捕捉傳入（非在此讀
    /// snapshot），避免快速連續切換 A→B 時 task-A 讀到 B 的時戳、push 出 (idA, tsB) 不一致對。
    func pushActiveNotebook(_ id: String, updatedAt: Double?, authManager: any AuthManaging, kgService: any KGServing) async {
        guard authManager.isLoggedIn else { return }
        do {
            _ = try await kgService.updateVocabUIConfig(
                KGVocabUIConfig(active_notebook_id: id, updated_at: updatedAt)
            )
        } catch {
            AppLog.kg.warning("pushActiveNotebook failed: \(error.localizedDescription)")
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
            // local-only / 未同步本子在 server 上沒有對應紀錄，呼叫 server delete 會 404
            // 並讓整個刪除 throw → 本地永遠刪不掉（孤兒 local-* 預設本即此類）。
            // 直接跳過 server、只做本地刪除。
            let isLocalOnly = deletedId.hasPrefix("local-") || notebook.syncStatus == 0
            if !isLocalOnly {
                try await kgService.deleteNotebook(id: deletedId)
            }

            NotebookReconciler.cascadeDeleteEntries(
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
            notebook.isSoftDeleted = true
            notebook.updatedAt = Date()

            // Hard guarantee mirror of the reconcile-path UserDefaults cleanup:
            // even if `setActiveNotebook` was a no-op (caller injection 不保證寫入)
            // 或 `resolveFallbackNotebookId` 回傳 nil（only-notebook edge case），
            // 直接清掉指向 deletedId 的 stale activeNotebookId，避免 Book.resolvedNotebookId
            // 之後 fall through 到死 id。
            if ActiveNotebookStore.shared.activeNotebookIdIfSet == deletedId {
                ActiveNotebookStore.shared.clearStale()
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
        let candidates = notebooks.filter { !$0.isSoftDeleted && $0.remoteId != deletedId }
        if let def = candidates.first(where: { $0.isDefault }) {
            return def.remoteId
        }
        return candidates.first?.remoteId
    }
}
