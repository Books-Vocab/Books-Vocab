import Foundation
import Observation
import SwiftData

@Observable @MainActor
final class WordDetailSceneState {
    var presenterState: WordDetailPresenter.State?
    /// 詳情頁單一錯誤 banner 的來源。原名 `linkError`，在封存進入本場景後改為泛稱
    /// ——同一條 banner 服務所有卡片層級動作，不再只服務知識連結。
    ///
    /// **生命週期規則**：錯誤帶 `ActionKind`，成功時**只清掉同類動作**留下的訊息。
    ///
    /// 兩個方向都要防，而且它們互相拉扯：
    /// - 只寫不清 → 失敗訊息活過後續的成功動作（封存失敗 → 再按一次成功 → 圖示已翻成
    ///   `archivebox.fill`，banner 還掛著「封存失敗」）。
    /// - 每個動作起手就無差別清空 → 反而**吃掉使用者還沒讀的錯誤**。連結操作是
    ///   fire-and-forget：dispatch 時清、completion 時才寫，所以「刪除連結失敗」（已靜靜
    ///   回捲、列自己長回來，訊息是唯一的解釋）會被隨後一次成功的封存抹掉。
    ///
    /// 依 kind 配對就沒有這個取捨：封存成功只清封存的錯，連結成功只清連結的錯。
    var actionError: String?

    /// `actionError` 的來源分類。單槽 banner 沒有它就無法分辨「這則訊息是誰留的」。
    private var actionErrorKind: ActionKind?

    enum ActionKind: Equatable {
        case archive
        case link
        /// Reader 可見度切換。自成一類而非併入 `.link`：它與知識連結無關，
        /// 併進去會讓一次成功的連結操作清掉使用者還沒讀到的可見度錯誤。
        case readerVisibility
    }

    /// Reader 可見度存檔失敗的回報入口。`setActionError` 是 private（刻意的——
    /// 每則訊息都必須帶 kind），而這個失敗發生在 `WordDetailSheet` 的 closure 裡，
    /// 所以需要一個帶 kind 的公開入口；直接寫 `actionError` 會留下**上一則錯誤的
    /// kind**，讓後續同類的成功把這則訊息誤清掉。
    func reportReaderVisibilitySaveFailure() {
        setActionError(L10n.string("readerVisibility.saveFailed"), kind: .readerVisibility)
    }

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
        actionErrorKind = nil
    }

    private func setActionError(_ message: String, kind: ActionKind) {
        actionError = message
        actionErrorKind = kind
    }

    /// 成功收尾時呼叫：**只**清掉同類動作留下的錯誤，別類的留著給它自己的主人處理。
    private func clearActionError(for kind: ActionKind) {
        guard actionErrorKind == kind else { return }
        actionError = nil
        actionErrorKind = nil
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
            clearActionError(for: .archive)
        } catch {
            AppLog.kg.error("setArchived(\(archived)) failed '\(word)': \(error.localizedDescription)")
            setActionError(
                archived ? L10n.string("封存失敗") : L10n.string("解除封存失敗"),
                kind: .archive
            )

            // 淺層防護：這張卡可能在 await 期間被硬刪（BackgroundSyncActor /
            // SyncCoordinator 都有這條路徑）。**不是保證**——`SyncCoordinator` 明寫
            // `PersistentModel.isDeleted` 不可當 save 後的生命週期契約（有回歸測試釘住），
            // 所以這裡擋得掉常見情形，擋不掉全部。
            guard !entry.isDeleted else { return }

            // Compare-and-swap 而非無條件寫回：await 期間背景 pull 可能帶回權威值並
            // markSynced()，無條件寫回 `previous` 會用舊值蓋掉新鮮值且不再推送。
            //
            // **殘留窗口（ABA，已知未解）**：若伺服器其實套用成功但回應遺失，而同期 pull
            // 剛好寫回同一個值，這個比較分不出「還停在我們的樂觀值」與「pull 剛寫了同值」，
            // 仍會回捲成本地與伺服器分歧。要真解需要版本標記而非值比較。窗口窄（遺失回應
            // ＋同期 pull），且嚴格優於無條件寫回，故先收斂到此。
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
                clearActionError(for: .link)
            } catch {
                VocabularyGraphLinkMutation.rollbackLinkRemoval(removed, source: entry, peer: peer)
                setActionError(L10n.string("刪除連結失敗"), kind: .link)
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
                clearActionError(for: .link)
            } catch {
                VocabularyGraphLinkMutation.setHidden(!hidden, for: link, source: entry, peer: peer)
                setActionError(hidden ? L10n.string("隱藏連結失敗") : L10n.string("恢復連結失敗"), kind: .link)
            }
        }
    }
}
