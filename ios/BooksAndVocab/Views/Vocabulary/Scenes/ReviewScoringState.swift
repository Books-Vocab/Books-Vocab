import Foundation

/// 純評分邏輯狀態 — 管理本次 session 的答題記錄與計數。
/// 不依賴導航、不依賴 DB、不依賴 autoplay。
@Observable @MainActor
final class ReviewScoringState {
    private(set) var submittedAnswers: [Int: TodayReviewState.SubmittedAnswer] = [:]
    private(set) var forgotCount = 0
    private(set) var rememberedCount = 0
    var rememberedFeedbackTrigger = 0
    var forgotFeedbackTrigger = 0

    @discardableResult
    func record(
        _ feedback: ReviewFeedback,
        at index: Int,
        reviewRecordID: UUID = UUID()
    ) -> TodayReviewState.SubmittedAnswer {
        let answer = TodayReviewState.SubmittedAnswer(
            feedback: feedback,
            answeredAt: Date(),
            reviewRecordID: reviewRecordID
        )
        submittedAnswers[index] = answer
        switch feedback {
        case .remembered:
            rememberedFeedbackTrigger += 1
            rememberedCount += 1
        case .forgot:
            forgotFeedbackTrigger += 1
            forgotCount += 1
        }
        return answer
    }

    func hasAnswer(at index: Int) -> Bool {
        submittedAnswers[index] != nil
    }

    /// Mark an answer as DB-flush-confirmed. Called from the flush success
    /// callback so the snapshot can record `flushed=true` and restore won't
    /// re-flush it. No-op if the index has no recorded answer.
    func markFlushed(at index: Int) {
        submittedAnswers[index]?.flushed = true
    }

    func restore(
        submittedAnswers: [Int: TodayReviewState.SubmittedAnswer],
        rememberedCount: Int,
        forgotCount: Int
    ) {
        self.submittedAnswers = submittedAnswers
        self.rememberedCount = rememberedCount
        self.forgotCount = forgotCount
    }
}
