#if os(macOS)
import SwiftUI

/// macOS split panel 共享狀態。
/// NotebookListView 持有，子頁透過 Environment 寫入。
/// Detail panel 是 NavigationStack 的兄弟（不在裡面），避免導航破壞。
@Observable @MainActor
final class MacDetailState {
    var selectedEntry: VocabularyEntry?
    var activeReviewSession: TodayReviewSession?
    var contextEntries: [VocabularyEntry] = []

    var hasDetail: Bool { selectedEntry != nil || activeReviewSession != nil }

    func showWordDetail(_ entry: VocabularyEntry, allEntries: [VocabularyEntry]) {
        activeReviewSession = nil
        selectedEntry = entry
        contextEntries = allEntries
    }

    func showReview(_ session: TodayReviewSession, allEntries: [VocabularyEntry]) {
        selectedEntry = nil
        activeReviewSession = session
        contextEntries = allEntries
    }

    func dismiss() {
        selectedEntry = nil
        activeReviewSession = nil
        contextEntries = []
    }
}

// MARK: - Environment Key

private struct MacDetailStateKey: EnvironmentKey {
    static let defaultValue: MacDetailState? = nil
}

extension EnvironmentValues {
    var macDetail: MacDetailState? {
        get { self[MacDetailStateKey.self] }
        set { self[MacDetailStateKey.self] = newValue }
    }
}
#endif
