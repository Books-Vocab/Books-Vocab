import Foundation
import Observation
import SwiftData

@Observable @MainActor
final class WordDetailSceneState {
    var presenterState: WordDetailPresenter.State?
    /// 詳情頁單一錯誤 banner 的來源。原名 `linkError`，在封存進入本場景後改為泛稱
    /// ——同一條 banner 服務所有卡片層級動作，不再只服務知識連結。
    ///
    /// **生命週期規則**：每個動作起手一律 `beginAction()` 清空。一條共用 banner 若只寫不清，
    /// 失敗訊息會活過後續的成功動作——封存失敗 → 再按一次成功 → 圖示已翻成 `archivebox.fill`
    /// 但 banner 還掛著「封存失敗」；跨領域更糟，「隱藏連結失敗」會壓在一次成功的封存上，
    /// 使用者無從分辨它在講哪個動作。
    var actionError: String?

    /// 封存的 in-flight 旗標。放在狀態物件而非 view，是為了讓這個單元自己安全：
    /// 若只靠呼叫端記得加 guard，兩次重疊呼叫會交錯（A 樂觀 true → B 樂觀 false →
    /// A 成功、B 失敗 → B 回捲寫回 true，而伺服器上是 false）。
    private var isSettingArchived = false

    func refreshPresentation(
        for entry: VocabularyEntry,
        in allEntries: [VocabularyEntry]
    ) {
        let lookup = VocabularyEntry.buildCardIdLookup(from: allEntries)
        presenterState = WordDetailPresentation.state(
            for: entry,
            in: allEntries,
            lookup: lookup
        )
    }

    func dismissActionError() {
        actionError = nil
    }

    /// 每個卡片層級動作的起手式：清掉上一個動作留下的錯誤，讓 banner 永遠只描述最近一次動作。
    private func beginAction() {
        actionError = nil
    }

    /// 封存 / 解除封存這張卡。
    ///
    /// 形狀對齊同檔的 `setLinkHidden`：先樂觀翻轉、再打伺服器、失敗回捲。與連結操作
    /// 不同的是本方法是 `async` 而非 fire-and-forget `Task {}` —— 呼叫端（詳情頁的封存
    /// 鈕）需要知道何時結束才能收掉 in-flight 狀態，且 `KGVocabCoordinator.handleBatchArchive`
    /// 已是 async，兩條封存路徑保持同一種可等待語意。
    ///
    /// 封存是 server-authoritative（無離線 outbox 動作），所以失敗必須完整回捲：
    /// 本機留著「已封存」而伺服器沒有，下次 pull 就會把卡片翻回來。
    func setArchived(
        _ archived: Bool,
        for entry: VocabularyEntry,
        kgService: any KGServing,
        modelContext: ModelContext
    ) async {
        let previous = entry.isArchived
        guard previous != archived, !isSettingArchived else { return }
        beginAction()
        isSettingArchived = true
        defer { isSettingArchived = false }

        let word = entry.word
        entry.isArchived = archived

        do {
            try await kgService.archiveCard(
                word: word,
                archived: archived,
                notebookId: entry.notebookId
            )
            modelContext.safeSave()
        } catch {
            AppLog.kg.error("setArchived(\(archived)) failed '\(word)': \(error.localizedDescription)")
            actionError = archived
                ? L10n.string("封存失敗")
                : L10n.string("解除封存失敗")

            // 這張卡可能在 await 期間被硬刪（BackgroundSyncActor / SyncCoordinator 都有
            // 這條路徑），碰已失效的 model 會 trap。
            guard !entry.isDeleted else { return }

            // Compare-and-swap 而非無條件寫回：await 期間背景 pull 可能帶回權威值並
            // markSynced()。若那時無條件寫回 `previous`，就會用舊值蓋掉新鮮的權威值，
            // 而且因為已 markSynced 不會再推上去——正好製造出這段註解宣稱要防止的
            // 「卡片自己復活」。只有在世界仍停在我們樂觀寫入的狀態時才回捲。
            guard entry.isArchived == archived else { return }
            entry.isArchived = previous
            // 回捲這一側才是真正需要顯式存檔的分支：它要把樂觀值從磁碟上撤下來。
            modelContext.safeSave()
        }
    }

    func linkedEntry(
        for link: KGCardLinkSummary,
        from entry: VocabularyEntry,
        in allEntries: [VocabularyEntry]
    ) -> VocabularyEntry? {
        let lookup = VocabularyEntry.buildCardIdLookup(from: allEntries)
        return entry.linkedEntry(for: link, lookup: lookup)
    }

    func addLink(
        target: VocabularyEntry,
        to entry: VocabularyEntry,
        kgService: any KGServing
    ) {
        guard let fromId = entry.kgCardId else { return }
        guard let pending = VocabularyGraphLinkMutation.beginManualLink(from: entry, to: target) else { return }
        beginAction()
        let notebookId = entry.notebookId

        Task { @MainActor in
            do {
                let link = try await kgService.createManualLink(
                    fromId: fromId,
                    toId: pending.targetCardId,
                    notebookId: notebookId
                )
                VocabularyGraphLinkMutation.commitManualLink(pending, result: link, on: entry)
            } catch {
                VocabularyGraphLinkMutation.rollbackManualLink(pending, on: entry)
                actionError = L10n.string("新增連結失敗")
            }
        }
    }

    func deleteLink(
        _ link: KGCardLinkSummary,
        from entry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        kgService: any KGServing
    ) {
        beginAction()
        let notebookId = entry.notebookId
        let peer = linkedEntry(for: link, from: entry, in: allEntries)
        let removed = VocabularyGraphLinkMutation.removeLink(link, from: entry, peer: peer)

        Task { @MainActor in
            do {
                try await kgService.deleteLink(linkId: link.id, notebookId: notebookId)
            } catch {
                VocabularyGraphLinkMutation.rollbackLinkRemoval(removed, source: entry, peer: peer)
                actionError = L10n.string("刪除連結失敗")
            }
        }
    }

    func hideLink(
        _ link: KGCardLinkSummary,
        from entry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        kgService: any KGServing
    ) {
        setLinkHidden(true, link: link, entry: entry, allEntries: allEntries, kgService: kgService)
    }

    func unhideLink(
        _ link: KGCardLinkSummary,
        from entry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        kgService: any KGServing
    ) {
        setLinkHidden(false, link: link, entry: entry, allEntries: allEntries, kgService: kgService)
    }

    private func setLinkHidden(
        _ hidden: Bool,
        link: KGCardLinkSummary,
        entry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        kgService: any KGServing
    ) {
        beginAction()
        let notebookId = entry.notebookId
        let peer = linkedEntry(for: link, from: entry, in: allEntries)
        VocabularyGraphLinkMutation.setHidden(hidden, for: link, source: entry, peer: peer)

        Task { @MainActor in
            do {
                if hidden {
                    try await kgService.hideLink(linkId: link.id, notebookId: notebookId)
                } else {
                    try await kgService.unhideLink(linkId: link.id, notebookId: notebookId)
                }
            } catch {
                VocabularyGraphLinkMutation.setHidden(!hidden, for: link, source: entry, peer: peer)
                actionError = hidden ? L10n.string("隱藏連結失敗") : L10n.string("恢復連結失敗")
            }
        }
    }
}
