import Foundation

/// 決定 podcast 字幕中哪些詞要上「詞庫螢光筆」底色。詞庫驅動、與 Reader 一致：凡屬於
/// 詞庫（含 rootForm / inflections，由 `ReaderVocabularyContext.lookedUpWords` 展開、
/// 全小寫）的詞，字幕對應的詞就上色。純函式、無狀態，供 cell 渲染與單元測試共用。
enum PodcastVocabHighlightResolver {
    /// 回傳 `words` 中命中詞庫的 index 集合。`lookedUp` 須為已小寫、含變形的詞集合
    /// （即 `translationHandler.lookedUpWords` 的 `Set`）。比對前對每個字幕詞做
    /// `normalize`（小寫 + 去頭尾標點），與 Reader 的詞庫比對語意一致。
    static func highlightedIndices(words: [String], lookedUp: Set<String>) -> Set<Int> {
        guard !lookedUp.isEmpty else { return [] }
        var result: Set<Int> = []
        for (index, word) in words.enumerated() {
            let normalized = normalize(word)
            guard !normalized.isEmpty else { continue }
            if lookedUp.contains(normalized) { result.insert(index) }
        }
        return result
    }

    /// 字幕詞 → 比對鍵：小寫 + 去「頭尾」標點。只去頭尾，所以詞內撇號（don't）、連字號
    /// （well-known）保留，與詞庫存字的形式對齊；包裹標點（"world," "(word)"）被剝除。
    static func normalize(_ word: String) -> String {
        word.lowercased().trimmingCharacters(in: .punctuationCharacters)
    }
}
