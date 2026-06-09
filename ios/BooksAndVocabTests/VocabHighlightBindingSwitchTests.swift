#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// Phase 1：換綁定單字本時，底線必須權威重畫。
///
/// 回歸 bug：BridgePlanner 舊版只看 `lookedUpWords.count` 決定加/減 highlight，
/// 換 notebook 後新舊單字數相同（或不同但內容互換）時不發任何 DOM 命令，
/// DOM 底線維持舊 notebook 的字。修法改為以 set 內容權威判斷：
/// 內容互換（有新增也有移除）時 clearAllVocabHighlights + 重 markVocabWords。
struct VocabHighlightBindingSwitchTests {
    @Test func setSwapWithEqualCountEmitsClearThenRemark() {
        var planner = BridgePlanner()
        let bookWords: Set<String> = ["alpha", "bravo", "charlie", "delta"]

        // 首次載入 bookUniqueWords + notebook A 的字
        let first = planner.makeCommands(from: makeSnapshot(
            lookedUpWords: ["alpha", "bravo"],
            bookUniqueWords: bookWords
        ))
        #expect(markedWords(in: first) == Set(["alpha", "bravo"]))

        // 同一份再餵一次：無變化
        let stable = planner.makeCommands(from: makeSnapshot(
            lookedUpWords: ["alpha", "bravo"],
            bookUniqueWords: bookWords
        ))
        #expect(domCommands(in: stable).isEmpty)

        // 換綁定 notebook B：字數相同(2==2) 但內容互換
        let swapped = planner.makeCommands(from: makeSnapshot(
            lookedUpWords: ["charlie", "delta"],
            bookUniqueWords: bookWords
        ))
        #expect(hasClearAllVocab(in: swapped))
        #expect(markedWords(in: swapped) == Set(["charlie", "delta"]))
        // clear 必須在 mark 之前
        #expect(clearPrecedesMark(in: swapped))
        // 互換只走 clearAll + markVocabWords，不得夾雜逐字 removeVocabWord
        #expect(removedWords(in: swapped).isEmpty)
    }

    @Test func pureRemovalDoesNotClearAll() {
        var planner = BridgePlanner()
        let bookWords: Set<String> = ["alpha", "bravo", "charlie"]
        _ = planner.makeCommands(from: makeSnapshot(
            lookedUpWords: ["alpha", "bravo", "charlie"],
            bookUniqueWords: bookWords
        ))
        // 移除單一字：用 removeVocabWord，不整片清
        let removed = planner.makeCommands(from: makeSnapshot(
            lookedUpWords: ["alpha", "bravo"],
            bookUniqueWords: bookWords
        ))
        #expect(!hasClearAllVocab(in: removed))
        #expect(removedWords(in: removed) == Set(["charlie"]))
    }

    @Test func pureAdditionOfSingleWordMarksIncrementally() {
        var planner = BridgePlanner()
        let bookWords: Set<String> = ["alpha", "bravo", "charlie"]
        _ = planner.makeCommands(from: makeSnapshot(
            lookedUpWords: ["alpha", "bravo"],
            bookUniqueWords: bookWords
        ))
        let added = planner.makeCommands(from: makeSnapshot(
            lookedUpWords: ["alpha", "bravo", "charlie"],
            bookUniqueWords: bookWords
        ))
        #expect(!hasClearAllVocab(in: added))
        #expect(newMarkedWords(in: added) == Set(["charlie"]))
    }

    // MARK: - Helpers

    /// 固定 trigger：避免每次 makeSnapshot 換 UUID 觸發 clearActiveHighlight 污染
    /// vocab highlight 斷言（clearActiveHighlight 屬選取態，與 vocab 底線無關）。
    private let fixedClearTrigger = UUID()

    private func makeSnapshot(
        lookedUpWords: [String],
        bookUniqueWords: Set<String>?
    ) -> ReadiumNavigatorView.BridgeSnapshot {
        .init(
            lookedUpWords: lookedUpWords,
            bookUniqueWords: bookUniqueWords,
            viewConfiguration: ReaderSettings.shared.viewConfiguration(systemColorScheme: .light),
            clearHighlightTrigger: fixedClearTrigger,
            removeWordTrigger: nil,
            navigateToLocator: nil,
            isInteractionBlocked: false
        )
    }

    private func domCommands(in commands: [BridgeCommand]) -> [DOMCommand] {
        commands.compactMap { if case .dom(let d) = $0 { return d } else { return nil } }
    }

    private func markedWords(in commands: [BridgeCommand]) -> Set<String> {
        for case .dom(.markVocabWords(let words)) in commands { return Set(words) }
        return []
    }

    private func newMarkedWords(in commands: [BridgeCommand]) -> Set<String> {
        var result = Set<String>()
        for case .dom(.markNewVocabWord(let word)) in commands { result.insert(word) }
        return result
    }

    private func removedWords(in commands: [BridgeCommand]) -> Set<String> {
        var result = Set<String>()
        for case .dom(.removeVocabWord(let word)) in commands { result.insert(word) }
        return result
    }

    private func hasClearAllVocab(in commands: [BridgeCommand]) -> Bool {
        for case .dom(.clearAllVocabHighlights) in commands { return true }
        return false
    }

    private func clearPrecedesMark(in commands: [BridgeCommand]) -> Bool {
        var clearIdx: Int?
        var markIdx: Int?
        for (i, command) in commands.enumerated() {
            if case .dom(.clearAllVocabHighlights) = command, clearIdx == nil { clearIdx = i }
            if case .dom(.markVocabWords) = command, markIdx == nil { markIdx = i }
        }
        guard let c = clearIdx, let m = markIdx else { return false }
        return c < m
    }
}
#endif
