import Foundation
import Testing
@testable import BooksBrowser

/// Covers `PodcastVocabHighlightResolver` — 詞庫驅動螢光筆的字幕詞 ↔ 詞庫比對。
/// `lookedUp` 模擬 `ReaderVocabularyContext.lookedUpWords` 的輸出（已小寫、含變形）。
struct PodcastVocabHighlightResolverTests {
    @Test func basicHitByExactWord() {
        let idx = PodcastVocabHighlightResolver.highlightedIndices(
            words: ["the", "quick", "fox"], lookedUp: ["quick"]
        )
        #expect(idx == [1])
    }

    /// 字幕詞大小寫不影響命中（normalize 小寫）。
    @Test func caseInsensitive() {
        let idx = PodcastVocabHighlightResolver.highlightedIndices(
            words: ["The", "QUICK", "Fox"], lookedUp: ["the", "quick", "fox"]
        )
        #expect(idx == [0, 1, 2])
    }

    /// 包裹標點（逗號、句點、括號、引號）被剝除後仍命中。
    @Test func wrappingPunctuationStripped() {
        let idx = PodcastVocabHighlightResolver.highlightedIndices(
            words: ["world,", "world.", "(world)", "\"world\""], lookedUp: ["world"]
        )
        #expect(idx == [0, 1, 2, 3])
    }

    /// 詞內撇號 / 連字號保留——只去頭尾標點，don't / well-known 不被破壞。
    @Test func innerApostropheAndHyphenPreserved() {
        let idx = PodcastVocabHighlightResolver.highlightedIndices(
            words: ["don't", "well-known", "can't,"], lookedUp: ["don't", "well-known", "can't"]
        )
        #expect(idx == [0, 1, 2])
    }

    /// 變形由 lookedUp 涵蓋（Reader 端已展開 inflections/rootForm），resolver 不做詞形還原。
    @Test func inflectionsHitViaLookedUpSet() {
        // lookedUp 含 lay 的變形（模擬 inflections 展開）
        let idx = PodcastVocabHighlightResolver.highlightedIndices(
            words: ["she", "laid", "it"], lookedUp: ["lay", "lays", "laid", "laying", "lain"]
        )
        #expect(idx == [1])
    }

    @Test func noHit() {
        let idx = PodcastVocabHighlightResolver.highlightedIndices(
            words: ["alpha", "beta"], lookedUp: ["gamma"]
        )
        #expect(idx.isEmpty)
    }

    /// 空詞庫 → 無命中（短路）。
    @Test func emptyLookedUpIsEmpty() {
        let idx = PodcastVocabHighlightResolver.highlightedIndices(
            words: ["alpha", "beta"], lookedUp: []
        )
        #expect(idx.isEmpty)
    }

    /// 純標點詞（破折號等）normalize 後為空 → 跳過，不誤命中空字串。
    @Test func purePunctuationSkipped() {
        let idx = PodcastVocabHighlightResolver.highlightedIndices(
            words: ["—", "...", "word"], lookedUp: ["word", ""]
        )
        #expect(idx == [2])
    }

    /// 同一詞在句中多次出現 → 全部命中（index 級，非去重字串）。
    @Test func repeatedWordAllIndices() {
        let idx = PodcastVocabHighlightResolver.highlightedIndices(
            words: ["run", "and", "run", "again"], lookedUp: ["run"]
        )
        #expect(idx == [0, 2])
    }
}
