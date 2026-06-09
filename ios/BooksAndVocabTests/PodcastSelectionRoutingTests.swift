import Testing
@testable import BooksAndVocab

/// `PodcastSelectionRouting` 的單字 vs 片語分流判定。podcast 字幕 edit menu
/// 「翻譯」依此把單字導向 word path（translateQuick + 字根還原 + 詞庫去重）、
/// 片語導向 phrase path，對齊 reader 的詞彙互動契約。
@Suite("PodcastSelectionRouting")
struct PodcastSelectionRoutingTests {
    @Test func singleWordIsWord() {
        #expect(PodcastSelectionRouting.isSingleWord("cleverness"))
        #expect(PodcastSelectionRouting.route(for: "cleverness") == .word)
    }

    @Test func multiWordPhraseIsPhrase() {
        #expect(!PodcastSelectionRouting.isSingleWord("improving on 100"))
        #expect(PodcastSelectionRouting.route(for: "most comfortable era") == .phrase)
    }

    @Test func surroundingWhitespaceStillSingleWord() {
        // 前後空白不影響「單一詞」判定（trim 後仍只有一個 token）。
        #expect(PodcastSelectionRouting.isSingleWord("  cleverness  "))
        #expect(PodcastSelectionRouting.route(for: "  cleverness  ") == .word)
    }

    @Test func punctuatedWordIsWord() {
        // 含內部標點但無空白者仍視為單一詞。
        #expect(PodcastSelectionRouting.isSingleWord("don't"))
        #expect(PodcastSelectionRouting.route(for: "well-being") == .word)
    }

    @Test func emptyOrBlankIsPhrase() {
        // 空 / 純空白沒有單一 token → 非單字（route 落 phrase；實務上 edit menu
        // 上游已擋空選取，此為純函式邊界防禦）。
        #expect(!PodcastSelectionRouting.isSingleWord(""))
        #expect(!PodcastSelectionRouting.isSingleWord("   "))
        #expect(PodcastSelectionRouting.route(for: "") == .phrase)
    }
}
