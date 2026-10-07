import Foundation

/// 複習卡上「這張卡來自哪一本單字本」的標示（#2040）。
///
/// 只有多單字本入口才畫：session 的卡片涵蓋 ≥2 個 `notebookId` 時，使用者看不出
/// 手上這張屬於哪一本；單一單字本入口全部來自同一本，標示只是雜訊。
struct ReviewCardNotebookBadge: Equatable {
    let notebookId: String
    /// 已解析好的顯示名稱；查不到單字本時是本地化備援文字，**永遠不是 id 字串**。
    let name: String
    /// `Notebook.color` 原值（hex）。nil ＝ 不畫色點（含單字本尚未同步的情況）。
    let colorHex: String?
}

enum ReviewCardNotebookBadgeResolver {
    /// session 是否跨單字本 —— 決定整個 session 要不要畫標示。
    static func spansMultipleNotebooks(_ sessionNotebookIDs: some Sequence<String>) -> Bool {
        var seen: String?
        for id in sessionNotebookIDs {
            guard let first = seen else {
                seen = id
                continue
            }
            if id != first { return true }
        }
        return false
    }

    /// session 內每個 notebookId 對應的標示；單一單字本入口回空表（不畫）。
    static func badges(
        sessionNotebookIDs: [String],
        notebooks: [Notebook]
    ) -> [String: ReviewCardNotebookBadge] {
        guard spansMultipleNotebooks(sessionNotebookIDs) else { return [:] }
        var result: [String: ReviewCardNotebookBadge] = [:]
        for id in sessionNotebookIDs where result[id] == nil {
            result[id] = badge(for: id, notebooks: notebooks)
        }
        return result
    }

    /// `entry.notebookId` 對 `Notebook.remoteId`。`"default"` 是 server-side sentinel
    /// （`ActiveNotebookStore.defaultNotebookId`），沒有同名 row 時改認 `isDefault` 那本。
    static func badge(for notebookId: String, notebooks: [Notebook]) -> ReviewCardNotebookBadge {
        let live = notebooks.filter { !$0.isSoftDeleted }
        let match = live.first { $0.remoteId == notebookId }
            ?? (notebookId == ActiveNotebookStore.defaultNotebookId ? live.first(where: \.isDefault) : nil)
        let trimmedName = match?.name.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let name: String = if !trimmedName.isEmpty {
            trimmedName
        } else if notebookId == ActiveNotebookStore.defaultNotebookId || match?.isDefault == true {
            L10n.string("todayReview.card.notebook.default")
        } else {
            L10n.string("todayReview.card.notebook.unnamed")
        }
        return ReviewCardNotebookBadge(notebookId: notebookId, name: name, colorHex: match?.color)
    }
}
