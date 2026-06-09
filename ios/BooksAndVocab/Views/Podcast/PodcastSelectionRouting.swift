import Foundation

/// podcast 字幕選取的單字 vs 片語分流（純函式）。edit menu「翻譯」依此把單一詞
/// 導向 word path（`translateQuick` → 字根還原 + 詞庫去重 + 既有條目直接載入），
/// 多詞片語導向 phrase path（`translatePhrase`），對齊 reader 的詞彙互動契約。
///
/// reader 靠「caret tap（單字）vs range selection（片語）」的手勢本質分流；podcast
/// 所有選取都從同一個 `UITextView` edit menu 出來，故改以選取的 token 數判定。
enum PodcastSelectionRouting {
    enum Route { case word, phrase }

    /// 選取文字是否為單一詞（無內部空白）。`split` 預設 omit 空 token，故前後空白
    /// 與全空白字串自然落空 → 非單字。
    static func isSingleWord(_ text: String) -> Bool {
        text.split(whereSeparator: \.isWhitespace).count == 1
    }

    static func route(for selectionText: String) -> Route {
        isSingleWord(selectionText) ? .word : .phrase
    }
}
