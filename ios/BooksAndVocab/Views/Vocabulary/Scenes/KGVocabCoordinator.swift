import Foundation
import SwiftData
import SwiftUI

@MainActor protocol KGVocabCoordinating: AnyObject, Observable {
    var isLoading: Bool { get }
    var errorMessage: String? { get }
    var selectedEntry: VocabularyEntry? { get set }
    func dismissBanner()
    func handleRowTap(_ entryID: UUID, syncedEntries: [VocabularyEntry])
    func handleDeleteTap(_ entryID: UUID, syncedEntries: [VocabularyEntry], modelContext: ModelContext, toastCoordinator: AppToastCoordinator)
    func loadInitialData(authManager: any AuthManaging, kgService: any KGServing, modelContext: ModelContext) async
    func forceRefresh(kgService: any KGServing, modelContext: ModelContext) async
    func retryPendingDeletes(
        pendingDeletes: [VocabularyEntry],
        kgService: any VocabularyDeleting & DictionaryServing & HealthChecking,
        modelContext: ModelContext
    ) async
    func handleBatchDelete(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], modelContext: ModelContext, toastCoordinator: AppToastCoordinator)
    func handleBatchArchive(_ entryIDs: Set<UUID>, syncedEntries: [VocabularyEntry], kgService: any KGServing, modelContext: ModelContext, toastCoordinator: AppToastCoordinator) async
}

@Observable @MainActor
final class KGVocabCoordinator: KGVocabCoordinating {
    var isLoading = false
    /// 錯誤 banner 的單一真相；`errorMessage` 由它衍生（保持 protocol / 既有讀者不變）。
    /// banner 呈現交給純函式 `KGVocabBanner.make`，依實際 error 型別決定文案 / glyph / 可否重試。
    var bannerError: KGVocabBannerError?
    var refreshSuccessMessage: String?
    var selectedEntry: VocabularyEntry?

    /// 衍生自 `bannerError`。滿足 `KGVocabCoordinating.errorMessage` 唯讀契約，
    /// 亦供 `KGVocabView` 的 empty-state / phase-change 判斷沿用。
    var errorMessage: String? { bannerError?.message }

    func dismissBanner() {
        bannerError = nil
        refreshSuccessMessage = nil
    }

    func handleRowTap(_ entryID: UUID, syncedEntries: [VocabularyEntry]) {
        selectedEntry = syncedEntries.first { $0.id == entryID }
    }

    func handleDeleteTap(
        _ entryID: UUID,
        syncedEntries: [VocabularyEntry],
        modelContext: ModelContext,
        toastCoordinator: AppToastCoordinator
    ) {
        guard let entry = syncedEntries.first(where: { $0.id == entryID }) else { return }
        entry.queueDelete()
        if modelContext.safeSaveWithToast(toastCoordinator) {
            toastCoordinator.success("已刪除".localized)
        }
    }

    func loadInitialData(
        authManager: any AuthManaging,
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        guard authManager.isLoggedIn else { return }

        // Demo 模式已有本地資料，不需呼叫 API
        if authManager.isDemoMode { return }

        isLoading = true
        defer { isLoading = false }

        await pullAndApplyResult(trigger: .automatic, kgService: kgService, modelContext: modelContext)
    }

    func forceRefresh(
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        isLoading = true
        defer { isLoading = false }

        async let health: Void = kgService.healthCheck()
        await pullAndApplyResult(trigger: .explicit, kgService: kgService, modelContext: modelContext)
        await health
    }

    /// 誰發起了這次同步 —— 決定「沒有變化」時要不要出聲。
    ///
    /// 對齊 `ExplicitSync` 已經定下的全 app 政策：**自動同步成功靜默、顯式同步成功回饋**。
    /// 使用者主動下拉需要知道手勢生效了；每次進頁面自動跑的那輪則不該搶版面。
    enum RefreshTrigger {
        /// 進入單字本時 `.task` 自動觸發。
        case automatic
        /// 使用者下拉刷新 / 按重試 / 空狀態 CTA。
        case explicit
    }

    private func pullAndApplyResult(
        trigger: RefreshTrigger,
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        do {
            let outcome = try await kgService.pullCardsToLocal(
                container: modelContext.container, progress: nil, notebookId: nil
            )
            // 同步本身刻意不可取消（跑在 KGService 的 unstructured Task 裡，已付出的
            // round trip 一定寫完）；可取消的是**等待的這一端**。使用者已經離開畫面時
            // 就別再改它的 banner ——「等待者」與「工作」在此分道。
            try Task.checkCancellation()
            bannerError = nil
            refreshSuccessMessage = Self.successMessage(for: outcome, trigger: trigger)
        } catch is CancellationError {
            // 換頁、view 重建、或這一輪被取代。那是生命週期事件，不是故障：使用者什麼
            // 都沒做錯，網路也沒壞。保持畫面原狀（不覆寫既有 banner、不謊報網路錯誤）。
            // 資料不會因此漏掉——pull 已在背景跑完並寫入。
            AppLog.kg.info("vocab refresh cancelled (trigger=\(String(describing: trigger))) — banner untouched")
        } catch {
            // 依實際 error 型別分類，而非一律「離線模式」（見 KGVocabBanner）。
            bannerError = KGVocabBannerErrorClassifier.refreshError(from: error)
            refreshSuccessMessage = nil
        }
    }

    /// 成功同步後該說什麼（`nil` = 什麼都不說）。
    ///
    /// 純函式，可單元測試。三條規則：
    /// 1. 真的有變化 → 一律報「已更新」，不分觸發來源。
    /// 2. 沒有變化 + 自動觸發 → **靜默**。這是原本每次進單字本都彈「單字庫已更新」的修正：
    ///    那則提示與實際同步結果無關，出現得太廉價，久了就沒人看。
    /// 3. 沒有變化 + 顯式觸發 → 回「已是最新」。使用者主動下拉，沉默會讓人以為刷新沒生效。
    static func successMessage(for outcome: KGPullOutcome, trigger: RefreshTrigger) -> String? {
        if outcome.hasChanges { return L10n.string("單字庫已更新") }
        switch trigger {
        case .automatic: return nil
        case .explicit: return L10n.string("單字庫已是最新")
        }
    }

    /// 待刪除 banner 的「重試」= outbox 的**第二條** drain。
    ///
    /// 它必須與 `SyncCoordinator.startSync` 用同一套 role 分流：legacy 的
    /// `batchDeleteCards` / `deleteCard` 以 `(word, notebookId)` 定位卡片，
    /// 而 server 那側的 content lookup 只認 `card_role == "learning"`
    /// （`vocab_crud.py` 的 `_batch_apply` / `_resolve_card_or_raise`）。字典卡
    /// 送進去只有兩種下場：落 `not_found` bucket → 本地把它當「刪除意圖已達成」
    /// 而 hard-delete，server 上的卡 / graph link / archive refcount 卻全都還在
    /// （永久分岔）；或 per-word fallback 永遠 404 → 卡在 failed+delete 反覆彈同
    /// 一個壞掉的 banner。字典卡一律走 `deleteDictionaryCard(cardId:notebookId:)`。
    func retryPendingDeletes(
        pendingDeletes: [VocabularyEntry],
        kgService: any VocabularyDeleting & DictionaryServing & HealthChecking,
        modelContext: ModelContext
    ) async {
        var failedCount = 0
        let (learningDeletes, dictionaryDeletes) = SyncCoordinator.partitionDeletesByRole(pendingDeletes)
        let grouped = Dictionary(grouping: learningDeletes, by: \.notebookId)

        for (nbId, entries) in grouped {
            let words = entries.map(\.word)
            do {
                let response = try await kgService.batchDeleteCards(words: words, notebookId: nbId)
                // not_found = 已不存在於 server → 刪除意圖已達成，與 deleted_words
                // 走同一條本地收斂路徑；否則該字永遠 failed+delete → 永久卡死重試。
                let resolvableSet = SyncCoordinator.locallyResolvableDeletes(from: response)
                for entry in entries {
                    if resolvableSet.contains(entry.word) {
                        modelContext.delete(entry)
                    } else {
                        failedCount += 1
                        AppLog.kg.error("batchDelete: word unresolved on server '\(entry.word)'")
                    }
                }
            } catch {
                // Fallback to per-word delete
                for entry in entries {
                    do {
                        try await kgService.deleteCard(word: entry.word, notebookId: entry.notebookId)
                        modelContext.delete(entry)
                    } catch {
                        failedCount += 1
                        AppLog.kg.error("deleteCard retry failed '\(entry.word)': \(error.localizedDescription)")
                    }
                }
            }
        }

        if !dictionaryDeletes.isEmpty {
            // Peers = 全部本地 row，不是 outbox：持有指向該字典卡的 link 的那張卡
            // 通常自己是 synced，只掃 outbox 會漏掉它、留下懸空的邊（同
            // `SyncCoordinator.startSync` 的理由）。
            let peers = (try? modelContext.fetch(FetchDescriptor<VocabularyEntry>()))
                ?? pendingDeletes
            let outcome = await SyncCoordinator.drainDictionaryDeletes(
                dictionaryDeletes,
                peers: peers,
                modelContext: modelContext
            ) { cardID, notebookID in
                try await kgService.deleteDictionaryCard(cardId: cardID, notebookId: notebookID)
            }
            failedCount += outcome.failedWords.count
        }

        modelContext.safeSave()

        if failedCount > 0 {
            bannerError = .pendingDeletesFailure(
                message: L10n.format("刪除失敗 %@ 筆，稍後將自動重試", "\(failedCount)")
            )
        } else {
            // 全數收斂成功 → 清空前次失敗殘留的 error banner，
            // 對齊 loadInitialData / forceRefresh 成功路徑的清空慣例。
            bannerError = nil
            refreshSuccessMessage = L10n.string("待刪除項目已同步")
        }

        await kgService.healthCheck()
    }

    func handleBatchDelete(
        _ entryIDs: Set<UUID>,
        syncedEntries: [VocabularyEntry],
        modelContext: ModelContext,
        toastCoordinator: AppToastCoordinator
    ) {
        let entries = syncedEntries.filter { entryIDs.contains($0.id) }
        for entry in entries {
            entry.queueDelete()
        }
        if modelContext.safeSaveWithToast(toastCoordinator) {
            toastCoordinator.success(L10n.format("已刪除 %@ 個", String(entries.count)))
        }
    }

    func handleBatchArchive(
        _ entryIDs: Set<UUID>,
        syncedEntries: [VocabularyEntry],
        kgService: any KGServing,
        modelContext: ModelContext,
        toastCoordinator: AppToastCoordinator
    ) async {
        let entries = syncedEntries.filter { entryIDs.contains($0.id) }
        var failCount = 0
        let grouped = Dictionary(grouping: entries, by: \.notebookId)

        for (nbId, nbEntries) in grouped {
            let words = nbEntries.map(\.word)
            do {
                let response = try await kgService.batchArchiveCards(words: words, archived: true, notebookId: nbId)
                let updatedSet = Self.locallyResolvableArchives(from: response)
                for entry in nbEntries {
                    if updatedSet.contains(entry.word) {
                        entry.isArchived = true
                    } else {
                        failCount += 1
                    }
                }
            } catch {
                // Fallback to per-word archive
                for entry in nbEntries {
                    do {
                        try await kgService.archiveCard(word: entry.word, archived: true, notebookId: entry.notebookId)
                        entry.isArchived = true
                    } catch {
                        failCount += 1
                        AppLog.kg.error("Batch archive failed '\(entry.word)': \(error.localizedDescription)")
                    }
                }
            }
        }
        if modelContext.safeSaveWithToast(toastCoordinator) {
            if failCount > 0 {
                let successCount = entries.count - failCount
                bannerError = .archivePartial(
                    message: L10n.format("%@/%@ 張卡片已封存，部分失敗", "\(successCount)", "\(entries.count)")
                )
            } else {
                // 全數封存成功 → 清空前次部分失敗殘留的 error banner，
                // 對齊 loadInitialData / forceRefresh 成功路徑的清空慣例。
                bannerError = nil
                refreshSuccessMessage = L10n.string("封存已同步")
                toastCoordinator.success(L10n.format("已封存 %@ 個", String(entries.count)))
            }
        }
    }

    static func locallyResolvableArchives(
        from response: KGBatchArchiveResponse
    ) -> Set<String> {
        Set(response.updated_words).union(response.not_found)
    }

}
