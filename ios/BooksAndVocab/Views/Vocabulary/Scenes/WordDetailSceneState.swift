import Foundation
import Observation
import SwiftData

@Observable @MainActor
final class WordDetailSceneState {
    var presenterState: WordDetailPresenter.State?
    /// 詳情頁單一錯誤 banner 的來源。原名 `linkError`，在封存進入本場景後改為泛稱
    /// ——同一條 banner 服務所有卡片層級動作，不再只服務知識連結。
    var actionError: String?

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
        guard previous != archived else { return }
        entry.isArchived = archived

        do {
            try await kgService.archiveCard(
                word: entry.word,
                archived: archived,
                notebookId: entry.notebookId
            )
            modelContext.safeSave()
        } catch {
            entry.isArchived = previous
            AppLog.kg.error("setArchived(\(archived)) failed '\(entry.word)': \(error.localizedDescription)")
            actionError = archived
                ? L10n.string("封存失敗")
                : L10n.string("解除封存失敗")
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
                actionError = "新增連結失敗".localized
            }
        }
    }

    func deleteLink(
        _ link: KGCardLinkSummary,
        from entry: VocabularyEntry,
        allEntries: [VocabularyEntry],
        kgService: any KGServing
    ) {
        let notebookId = entry.notebookId
        let peer = linkedEntry(for: link, from: entry, in: allEntries)
        let removed = VocabularyGraphLinkMutation.removeLink(link, from: entry, peer: peer)

        Task { @MainActor in
            do {
                try await kgService.deleteLink(linkId: link.id, notebookId: notebookId)
            } catch {
                VocabularyGraphLinkMutation.rollbackLinkRemoval(removed, source: entry, peer: peer)
                actionError = "刪除連結失敗".localized
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
                actionError = hidden ? "隱藏連結失敗".localized : "恢復連結失敗".localized
            }
        }
    }
}
