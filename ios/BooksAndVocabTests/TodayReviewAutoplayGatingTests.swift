//
//  TodayReviewAutoplayGatingTests.swift
//  Books & Vocab Tests
//
//  末卡死路:在最後一張卡且答案已翻開時,autoplay 無事可做——
//  loop 的完整生命週期是 `isPlaying = true` → 睡 stayDelay(快 2s / 正常 4s / 慢 8s)
//  → `advance()` 因 `canGoNext == false` 回 false → `stop()`。這是獨立於 observation
//  斷鏈的 bug:修好 observation 之後它不會消失,只會從「按了完全沒反應」變成
//  「播放列閃一下就退回去」。
//
//  正控優先:守衛的「沉默」只有在同一組測試也證明它會放行時才可信,所以每個
//  refuse 斷言都配一個 start 斷言。最關鍵的是 `autoplayCanAlwaysBeTurnedOff`——
//  守衛若擋到關閉方向,就等於親手重造使用者回報的「出不去」。
//

import Foundation
import Testing
@testable import BooksAndVocab

@MainActor
struct TodayReviewAutoplayGatingTests {

    private func makeState(cardCount: Int) -> TodayReviewState {
        let entries = (0..<cardCount).map { index -> VocabularyEntry in
            let entry = VocabularyEntry(
                word: "gate-\(UUID().uuidString.prefix(6))-\(index)",
                translation: "translation-\(index)",
                context: "A sample sentence for card \(index).",
                bookTitle: "Sample"
            )
            entry.markSynced()
            return entry
        }
        return TodayReviewState(entries: entries, allEntries: entries, currentUserID: nil)
    }

    // MARK: - Domain truth table

    @Test func canAutoplayCoversTheDeadEndOnly() {
        var session = TodayReviewSessionState(queue: ["alpha", "beta"])
        #expect(session.canAutoplay, "還有下一張時必須放行")

        session.advanceReveal()
        #expect(session.canAutoplay, "已翻面但還有下一張,autoplay 仍能推進")

        session.goNext()
        #expect(session.canAutoplay, "最後一張的正面:autoplay 至少還能翻面")

        session.advanceReveal()
        #expect(!session.canAutoplay, "最後一張且已翻面 = 無事可做,這才是死路")

        session.advanceAfterSubmission()
        #expect(session.isComplete)
        #expect(!session.canAutoplay, "session 已結束")
    }

    // MARK: - Intent gating(每個 refuse 都配正控)

    @Test func autoplayStartsWhenMoreCardsRemain() {
        let state = makeState(cardCount: 3)
        state.toggleAutoPlay()
        let started = state.isAutoPlaying
        state.stopAutoPlay()
        #expect(started, "正控:還有卡片時必須能開始播放")
    }

    @Test func autoplayStartsOnLastCardWhileAnswerHidden() {
        let state = makeState(cardCount: 1)
        state.toggleAutoPlay()
        let started = state.isAutoPlaying
        state.stopAutoPlay()
        #expect(started, "正控:最後一張的正面仍有「翻面」可做,不該被擋")
    }

    @Test func autoplayRefusedAtTheDeadEnd() {
        let state = makeState(cardCount: 1)
        state.advanceReveal()
        state.toggleAutoPlay()
        let started = state.isAutoPlaying
        state.stopAutoPlay()
        #expect(!started, "最後一張且已翻面時開播 = 睡完 stayDelay 才自殺,播放列閃一下就退回去")
    }

    @Test func autoplayCanAlwaysBeTurnedOff() {
        // 守衛只擋「開始」,不能擋「停止」——否則就是親手重造使用者回報的出不去。
        let state = makeState(cardCount: 2)
        state.toggleAutoPlay()
        #expect(state.isAutoPlaying)

        // 播到死路:推進到最後一張並翻面,此時 canAutoplay 已為 false。
        state.goNext()
        state.advanceReveal()
        state.toggleAutoPlay()
        #expect(!state.isAutoPlaying, "已在播放中時,關閉方向必須永遠放行")
    }
}
