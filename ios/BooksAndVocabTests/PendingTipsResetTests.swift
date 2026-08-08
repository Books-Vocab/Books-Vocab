//
//  PendingTipsResetTests.swift
//  Books & Vocab Tests
//
//  APP-20260806-498c25: 切語言在 Debug build 必崩。根因是 TipKit 要求
//  `Tips.resetDatastore()` 必須早於 `Tips.configure()`，而 setLanguage 在
//  configure 之後才呼叫它 → throw → catch 內的 assertionFailure trap。
//  修法把 reset 延到下次啟動、configure 之前執行，中間只留一個旗標。
//  本檔釘住那個旗標的契約，特別是「reset 失敗時旗標不得被清掉」——
//  否則 Release 會退回靜默失敗（TipKit 文案停在舊語言），正是票要修的事。
//

import Foundation
import Testing
@testable import BooksAndVocab

// .serialized: setLanguageMarksPendingReset mutates the AppLanguageStore.shared
// singleton + UserDefaults.standard, matching the other suites that touch it.
@Suite(.serialized) @MainActor
struct PendingTipsResetTests {

    private func makeDefaults(_ name: String) -> UserDefaults {
        let suite = "test.pendingTipsReset.\(name)"
        UserDefaults.standard.removePersistentDomain(forName: suite)
        return UserDefaults(suiteName: suite)!
    }

    @Test func markMakesResetPending() {
        let defaults = makeDefaults(#function)
        #expect(PendingTipsReset.isPending(in: defaults) == false)

        PendingTipsReset.mark(in: defaults)

        #expect(PendingTipsReset.isPending(in: defaults))
    }

    @Test func consumeRunsResetAndClearsFlagOnSuccess() {
        let defaults = makeDefaults(#function)
        PendingTipsReset.mark(in: defaults)
        var resetCount = 0

        PendingTipsReset.consume(in: defaults) { resetCount += 1 }

        #expect(resetCount == 1)
        #expect(PendingTipsReset.isPending(in: defaults) == false)
    }

    @Test func consumeSkipsResetWhenNothingPending() {
        let defaults = makeDefaults(#function)
        var resetCount = 0

        PendingTipsReset.consume(in: defaults) { resetCount += 1 }

        #expect(resetCount == 0)
    }

    /// 語言切換會因 `.id(appLanguage.selection)` 重建整棵 view tree，於是
    /// 啟動用的 `.task` 在**同一個 process** 內再跑一次——此時 TipKit 已
    /// configure，reset 必然 throw。旗標若在那時被清掉，這次語言切換就永遠
    /// 等不到 reset。所以失敗必須保留旗標，留給下次冷啟動（configure 之前）。
    @Test func consumeKeepsFlagWhenResetFails() {
        let defaults = makeDefaults(#function)
        PendingTipsReset.mark(in: defaults)

        PendingTipsReset.consume(in: defaults) {
            throw NSError(domain: "TipKitTest", code: 1)
        }

        #expect(PendingTipsReset.isPending(in: defaults))
    }

    @Test func consumeIsIdempotentAfterSuccess() {
        let defaults = makeDefaults(#function)
        PendingTipsReset.mark(in: defaults)
        var resetCount = 0

        PendingTipsReset.consume(in: defaults) { resetCount += 1 }
        PendingTipsReset.consume(in: defaults) { resetCount += 1 }

        #expect(resetCount == 1)
    }

    /// 整合面：切語言必須留下待辦旗標（而不是就地 reset）。
    /// 這條跑在 shared singleton + `.standard` 上，抗併發靠兩件事，不是靠
    /// 「別人只會把旗標推向 true」（那句反而正是唯一的假綠路徑）：
    ///  (a) 本 suite 與其餘會動 AppLanguageStore.shared 的 suite 全是 @MainActor，
    ///      而本函式非 async、body 內無 suspension point ⇒ 單一 main-actor job，
    ///      插不進別的測試；
    ///  (b) 即使插得進來，`.standard` 上該 key 的唯一寫入者仍是 setLanguage→mark，
    ///      所以「mark 被拿掉」這個回歸必紅。
    @Test func setLanguageMarksPendingReset() {
        let store = AppLanguageStore.shared
        store.setLanguage(.english)
        PendingTipsReset.clear(in: .standard)
        defer {
            store.setLanguage(.system)
            PendingTipsReset.clear(in: .standard)
        }

        store.setLanguage(.japanese)

        #expect(PendingTipsReset.isPending(in: .standard))
    }
}
