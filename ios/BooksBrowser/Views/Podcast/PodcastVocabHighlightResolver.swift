import Foundation

/// 決定 podcast 字幕中哪些詞要上「詞庫螢光筆」底色。詞庫驅動、與 Reader 一致：凡屬於
/// 詞庫（含 rootForm / inflections，由 `ReaderVocabularyContext.lookedUpWords` 展開、
/// 全小寫）的詞，字幕對應的詞就上色。純函式、無狀態，供 cell 渲染與單元測試共用。
enum PodcastVocabHighlightResolver {
    /// 回傳 `words` 中命中詞庫的 word index 集合。`normalizedLookedUp` 須為**已用
    /// `normalize` 正規化過**的詞集合（呼叫端每次 render 算一次即可，避免 per-cell 重算）;
    /// 來源是 `translationHandler.lookedUpWords`（已小寫、含變形）。比對對稱:兩側都過
    /// `normalize`，確保撇號折疊一致。
    static func highlightedIndices(words: [String], normalizedLookedUp: Set<String>) -> Set<Int> {
        guard !normalizedLookedUp.isEmpty else { return [] }
        var result: Set<Int> = []
        for (index, word) in words.enumerated() {
            let normalized = normalize(word)
            guard !normalized.isEmpty else { continue }
            if normalizedLookedUp.contains(normalized) { result.insert(index) }
        }
        return result
    }

    /// 比對鍵正規化:折疊彎引號撇號（U+2019 → U+0027 直撇號）+ 小寫 + 去「頭尾」標點。
    /// - 撇號折疊是關鍵:字幕由 LLM/TTS 生成多用彎撇號，詞庫存字常用直撇號，不折疊會讓
    ///   don/can/I 等高頻縮寫的撇號形式 silent 不命中。兩側皆過此函式故對稱。
    /// - 只去**頭尾**標點:詞內撇號、連字號（well-known）保留;包裹標點（逗號、句點、括號、
    ///   引號）被剝除。
    static func normalize(_ word: String) -> String {
        word
            .replacingOccurrences(of: "\u{2019}", with: "'")
            .lowercased()
            .trimmingCharacters(in: .punctuationCharacters)
    }
}
