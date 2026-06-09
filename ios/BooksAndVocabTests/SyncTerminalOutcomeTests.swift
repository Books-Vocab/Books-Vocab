import Testing
@testable import BooksAndVocab

/// 覆蓋 `syncTerminalOutcome` 純函式 — sync pipeline 收尾的終態分類。
///
/// 回歸保護:cancel 後不可被 success path / catch path(CancellationError)
/// 覆寫成 .partial / .full。`wasCancelled` 一律壓過其他訊號。
@Suite("SyncTerminalOutcome")
struct SyncTerminalOutcomeTests {

    // MARK: - cancel 壓過一切(核心回歸)

    @Test("cancel + catch 拋 CancellationError → 維持 .cancelled,不覆寫成 .full")
    func cancelBeatsThrownError() {
        let outcome = syncTerminalOutcome(
            wasCancelled: true,
            thrownError: true,
            encounteredFailure: false
        )
        #expect(outcome == .keepCancelled)
    }

    @Test("cancel + success path 部分失敗 → 維持 .cancelled,不覆寫成 .partial")
    func cancelBeatsPartial() {
        let outcome = syncTerminalOutcome(
            wasCancelled: true,
            thrownError: false,
            encounteredFailure: true
        )
        #expect(outcome == .keepCancelled)
    }

    @Test("cancel + 全綠收尾(break 正常結束) → 維持 .cancelled,不覆寫成 .completed")
    func cancelBeatsCompleted() {
        let outcome = syncTerminalOutcome(
            wasCancelled: true,
            thrownError: false,
            encounteredFailure: false
        )
        #expect(outcome == .keepCancelled)
    }

    // MARK: - 非 cancel 的真實終態不受影響

    @Test("非 cancel + catch 拋真實錯誤 → .fullFailure")
    func realErrorBecomesFull() {
        let outcome = syncTerminalOutcome(
            wasCancelled: false,
            thrownError: true,
            encounteredFailure: false
        )
        #expect(outcome == .fullFailure)
    }

    @Test("非 cancel + 部分失敗 → .partial")
    func partialFailureStays() {
        let outcome = syncTerminalOutcome(
            wasCancelled: false,
            thrownError: false,
            encounteredFailure: true
        )
        #expect(outcome == .partial)
    }

    @Test("非 cancel + 全綠 → .completed")
    func cleanRunCompletes() {
        let outcome = syncTerminalOutcome(
            wasCancelled: false,
            thrownError: false,
            encounteredFailure: false
        )
        #expect(outcome == .completed)
    }

    // MARK: - 優先級:thrownError 壓過 encounteredFailure

    @Test("非 cancel + 拋錯 + 同時有部分失敗 → .fullFailure(thrown 優先)")
    func thrownBeatsPartial() {
        let outcome = syncTerminalOutcome(
            wasCancelled: false,
            thrownError: true,
            encounteredFailure: true
        )
        #expect(outcome == .fullFailure)
    }
}
