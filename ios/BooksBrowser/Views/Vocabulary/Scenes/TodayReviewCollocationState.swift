import Foundation

struct TodayReviewCollocationState {
    private(set) var explanations: [String: String] = [:]

    mutating func sync(from entry: VocabularyEntry?) {
        explanations = entry?.collocationExplanations ?? [:]
    }

    mutating func update(
        _ explanation: String?,
        for collocation: String,
        entry: VocabularyEntry?
    ) {
        guard let entry else {
            explanations = [:]
            return
        }

        var updated = explanations
        if let explanation {
            updated[collocation] = explanation
        } else {
            updated.removeValue(forKey: collocation)
        }
        explanations = updated
        entry.collocationExplanations = updated
    }
}
