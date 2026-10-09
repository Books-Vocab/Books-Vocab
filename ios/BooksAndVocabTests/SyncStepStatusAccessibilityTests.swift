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

    @Test("every state has a distinct, localized value", arguments: languages)
    func distinctValuePerState(language: AppLanguage) {
        let values = Self.all.map { $0.accessibilityValue(language: language) }
        #expect(Set(values).count == Self.all.count, "retry and running must not share one string")
        for (status, value) in zip(Self.all, values) {
            #expect(!value.isEmpty)
            #expect(!value.isEmpty, "\(status) unlocalized for \(language)")
        }
    }

    @Test("the step value appends progress or detail")
    func stepValueCarriesProgress() {
        var step = PipelineStep(id: "pull", label: "pull", status: .running, current: 3, total: 9)
        #expect(step.accessibilityValue(language: .english) == "In progress，3/9")
        step.status = .error
        step.detail = "boom"
        #expect(step.accessibilityValue(language: .english) == "Failed，boom")
    }
}
