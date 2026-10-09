import Foundation
import Testing
@testable import BooksAndVocab

/// #2432: the six sync step states were conveyed only by icon shape/colour.
/// VoiceOver needs one distinct localized value per state, shared by the
/// vocab sync screen and the Settings progress panel.
@Suite("Sync step status accessibility (#2432)", .serialized)
struct SyncStepStatusAccessibilityTests {
    private static let languages: [AppLanguage] = [
        .english, .traditionalChinese, .simplifiedChinese, .japanese, .korean,
    ]
    private static let all: [PipelineStep.StepStatus] = [.waiting, .running, .retry, .done, .skipped, .error]

    /// Exact per-language strings, in `all` order. Pinning literals (not just
    /// "non-empty") turns a missing lproj entry red, since L10n falls back to the key.
    private static let expected: [AppLanguage: [String]] = [
        .english: ["Waiting", "In progress", "Retrying", "Done", "Skipped", "Failed"],
        .traditionalChinese: ["等待中", "進行中", "重試中", "已完成", "已略過", "失敗"],
        .simplifiedChinese: ["等待中", "进行中", "重试中", "已完成", "已跳过", "失败"],
        .japanese: ["待機中", "実行中", "再試行中", "完了", "スキップ", "失敗"],
        .korean: ["대기 중", "진행 중", "재시도 중", "완료", "건너뜀", "실패"],
    ]

    @Test("every state has a distinct, localized value", arguments: languages)
    func distinctValuePerState(language: AppLanguage) {
        let values = Self.all.map { $0.accessibilityValue(language: language) }
        #expect(Set(values).count == Self.all.count, "retry and running must not share one string")
        #expect(values == Self.expected[language])
    }

    @Test("the step value appends progress or detail")
    func stepValueCarriesProgress() {
        var step = PipelineStep(id: "pull", label: "pull", status: .running, current: 3, total: 9)
        #expect(step.accessibilityValue(language: .english) == "In progress，3/9")
        step.status = .error
        step.detail = "boom"
        #expect(step.accessibilityValue(language: .english) == "Failed，boom")
    }

    @Test("a waiting step never speaks its hidden detail")
    func waitingStepOmitsDetail() {
        var step = PipelineStep(id: "pull", label: "pull", status: .waiting, current: 0, total: 0)
        step.detail = "hidden"
        #expect(step.accessibilityValue(language: .english) == "Waiting")
    }

    @Test("row summary localizes the label and carries the state value", arguments: languages)
    func rowSummary(language: AppLanguage) {
        let step = PipelineStep(id: "retry", label: "重試中", status: .retry, current: 0, total: 0)
        let summary = step.accessibilitySummary(language: language)
        #expect(summary.label == Self.expected[language]?[2])
        #expect(summary.value == Self.expected[language]?[2])
    }
}
