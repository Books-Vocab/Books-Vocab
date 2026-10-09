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

    @Test func discardIsCaseInsensitive() {
        let pending = PendingVocabMarks()
        pending.enqueue(["Alpha", "bravo"])
        pending.discard(word: "ALPHA")
        #expect(pending.drain() == ["bravo"])
    }

    // MARK: - scheduler wiring (debounce + emit)

    private final class Sink: @unchecked Sendable {
        private let lock = NSLock()
        private var batches: [[String]] = []
        func record(_ words: [String]) { lock.lock(); batches.append(words); lock.unlock() }
        var all: [[String]] { lock.lock(); defer { lock.unlock() }; return batches }
    }

    private func makeScheduler(_ sink: Sink) -> VocabMarkScheduler {
        VocabMarkScheduler(duration: 0.05) { sink.record($0) }
    }

    private func settle() async { try? await Task.sleep(for: .seconds(0.4)) }

    @Test func removeDuringWindowEmitsOnlyRemainingWord() async {
        let sink = Sink()
        let scheduler = makeScheduler(sink)
        scheduler.schedule(["X", "Y"])
        scheduler.discard(word: "X")
        await settle()
        #expect(sink.all == [["Y"]])
    }

    @Test func clearAllDuringWindowEmitsNothing() async {
        let sink = Sink()
        let scheduler = makeScheduler(sink)
        scheduler.schedule(["X", "Y"])
        scheduler.discardAll()
        await settle()
        #expect(sink.all.isEmpty)
    }

    @Test func repeatedSchedulesCoalesceIntoOneEmit() async {
        let sink = Sink()
        let scheduler = makeScheduler(sink)
        scheduler.schedule(["X"])
        scheduler.schedule(["X", "Y"])
        scheduler.schedule(["Z"])
        await settle()
        #expect(sink.all == [["X", "Y", "Z"]])
    }

    @Test func deallocatedSchedulerEmitsNothing() async {
        let sink = Sink()
        var scheduler: VocabMarkScheduler? = makeScheduler(sink)
        scheduler?.schedule(["X"])
        scheduler = nil
        await settle()
        #expect(sink.all.isEmpty)
    }
}
#endif
