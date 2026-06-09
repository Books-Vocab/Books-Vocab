#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Phase 2：每本書綁定恰好一個真實單字本，scope 釘死不漂移。
///
/// `ensureBoundNotebook(seed:)` 在書首次開啟（未綁定）時以 seed（最近使用的真實
/// 單字本）固化綁定，之後不再 runtime fallback 到全域 active —— 消除「底線快照
/// scope」與「點擊查詢 scope」因全域 active 中途改變而不一致的 cache miss。
struct BookNotebookBindingTests {
    private func makeBook() -> Book {
        Book(title: "t", author: "a", fileName: "f.epub")
    }

    @Test func seedsBindingWhenUnbound() {
        let book = makeBook()
        #expect(book.preferredNotebookId == nil)

        let resolved = book.ensureBoundNotebook(seed: "nb-x")

        #expect(resolved == "nb-x")
        #expect(book.preferredNotebookId == "nb-x")
    }

    @Test func doesNotOverrideExistingBinding() {
        let book = makeBook()
        book.preferredNotebookId = "nb-a"

        let resolved = book.ensureBoundNotebook(seed: "nb-y")

        #expect(resolved == "nb-a")          // 不覆寫既有綁定
        #expect(book.preferredNotebookId == "nb-a")
    }

    @Test func seedingIsIdempotent() {
        let book = makeBook()
        _ = book.ensureBoundNotebook(seed: "nb-x")
        _ = book.ensureBoundNotebook(seed: "nb-z")  // 第二次帶不同 seed
        #expect(book.preferredNotebookId == "nb-x") // 仍維持首次固化值
    }
}
#endif
