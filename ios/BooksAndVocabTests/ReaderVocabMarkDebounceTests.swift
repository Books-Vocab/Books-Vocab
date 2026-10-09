#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// #2437：markVocabWords 經 0.8s debounce 才送出；debounce 窗口內若發生
/// removeVocabWord / clearAllVocabHighlights，待送單字必須同步剔除，
/// 否則 debounce 觸發時會把已移除的底線重新畫回去。
struct ReaderVocabMarkDebounceTests {
    @Test func drainReturnsEnqueuedWordsOnceInOrder() {
        let pending = PendingVocabMarks()
        pending.enqueue(["alpha", "bravo"])
        pending.enqueue(["bravo", "charlie"])
        #expect(pending.drain() == ["alpha", "bravo", "charlie"])
        #expect(pending.drain().isEmpty)
    }

    @Test func removeDuringDebounceWindowDropsOnlyThatWord() {
        let pending = PendingVocabMarks()
        pending.enqueue(["alpha", "bravo", "charlie"])
        pending.discard(word: "bravo")
        #expect(pending.drain() == ["alpha", "charlie"])
    }

    @Test func clearAllDuringDebounceWindowDropsEverything() {
        let pending = PendingVocabMarks()
        pending.enqueue(["alpha", "bravo"])
        pending.discardAll()
        #expect(pending.drain().isEmpty)
    }

    @Test func clearThenRemarkKeepsOnlyTheNewWords() {
        let pending = PendingVocabMarks()
        pending.enqueue(["alpha", "bravo"])
        pending.discardAll()
        pending.enqueue(["charlie"])
        #expect(pending.drain() == ["charlie"])
    }
}
#endif
