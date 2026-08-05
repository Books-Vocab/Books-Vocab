#if os(iOS)
import Foundation

/// 單字詳情頁文案集中地，慣例對齊 `NotebookListCopy` / `NotebookEditCopy`。
enum WordDetailCopy {
    static var archive: String { L10n.string("封存") }
    static var unarchive: String { L10n.string("解除封存") }
    static var delete: String { L10n.string("刪除") }
    static var cancel: String { L10n.string("取消") }
    static var deleted: String { L10n.string("已刪除") }
    static var excludeFromReader: String { L10n.string("閱讀時不標記此單字") }

    static func deleteTitle(word: String) -> String {
        L10n.format("刪除「%@」？", word)
    }

    /// 刪除確認要**指名損失**，而不是問一句空泛的「確定嗎」。連結數就寫在同一個畫面上，
    /// app 既然知道確切數字，就該在使用者按下去之前說出來。
    static func deleteMessage(linkCount: Int) -> String {
        linkCount > 0
            ? L10n.format("複習紀錄與 %@ 條知識連結會一併移除，無法復原。", "\(linkCount)")
            : L10n.string("複習紀錄會一併移除，無法復原。")
    }
}
#endif
