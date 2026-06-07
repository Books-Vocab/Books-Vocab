#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for `PendingVocabPresenter` — the local pending-vocab inbox shown before sync.
///
/// 直接餵合成的 `PendingVocabPresenterState`（純值型別，無 @MainActor init），
/// 故不需要 View-scene 包裝；所有 closures 為無副作用 no-op。
/// 覆蓋：混合 add/delete 列、純新增、壓力（多列）、空狀態三種 description 分支。
enum PendingVocabPresenterScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "Pending Vocab Presenter") {
            Scenario("Populated · add + delete mix", layout: .fill) {
                presenter(state: Self.mixedState)
            }
            Scenario("Populated · adds only", layout: .fill) {
                presenter(state: Self.addsOnlyState)
            }
            Scenario("Populated · stress (long list)", layout: .fill) {
                presenter(state: Self.stressState)
            }
            Scenario("Empty · nothing collected", layout: .fill) {
                presenter(state: Self.emptyFreshState)
            }
            Scenario("Empty · has knowledge with due", layout: .fill) {
                presenter(state: Self.emptyWithDueState)
            }
        }
    }

    // MARK: - Presenter wrapper

    private static func presenter(state: PendingVocabPresenterState) -> some View {
        AppThemeContainer {
            PendingVocabPresenter(
                state: state,
                onRowTapped: { _ in },
                onActionTapped: { _ in },
                onSwitchToKnowledge: {}
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: - States

    private static var mixedState: PendingVocabPresenterState {
        let rows = [
            pendingRow(word: "ephemeral", pos: "adj.", translation: "短暫的", action: .add),
            pendingRow(word: "ubiquitous", pos: "adj.", translation: "無所不在的", action: .add),
            pendingRow(word: "obsolete", pos: "adj.", translation: "過時的", action: .delete)
        ]
        return PendingVocabPresenterState(
            pendingCount: rows.count,
            rows: rows,
            knowledgeCount: 128,
            dueCount: 7
        )
    }

    private static var addsOnlyState: PendingVocabPresenterState {
        let rows = [
            pendingRow(word: "serendipity", pos: "n.", translation: "意外的好運", action: .add),
            pendingRow(word: "lucid", pos: "adj.", translation: "清晰的", action: .add)
        ]
        return PendingVocabPresenterState(
            pendingCount: rows.count,
            rows: rows,
            knowledgeCount: 40,
            dueCount: 0
        )
    }

    private static var stressState: PendingVocabPresenterState {
        let words: [(String, String, String, PendingAction)] = [
            ("perfunctory", "adj.", "敷衍的", .add),
            ("quintessential", "adj.", "典型的", .add),
            ("recalcitrant", "adj.", "頑抗的", .delete),
            ("sycophant", "n.", "諂媚者", .add),
            ("taciturn", "adj.", "沉默寡言的", .add),
            ("vicarious", "adj.", "感同身受的", .delete),
            ("wistful", "adj.", "惆悵的", .add),
            ("zealous", "adj.", "熱忱的", .add)
        ]
        let rows = words.map { pendingRow(word: $0.0, pos: $0.1, translation: $0.2, action: $0.3) }
        return PendingVocabPresenterState(
            pendingCount: rows.count,
            rows: rows,
            knowledgeCount: 512,
            dueCount: 33
        )
    }

    private static var emptyFreshState: PendingVocabPresenterState {
        PendingVocabPresenterState(
            pendingCount: 0,
            rows: [],
            knowledgeCount: 0,
            dueCount: 0
        )
    }

    private static var emptyWithDueState: PendingVocabPresenterState {
        PendingVocabPresenterState(
            pendingCount: 0,
            rows: [],
            knowledgeCount: 96,
            dueCount: 12
        )
    }

    // MARK: - Fixtures

    private enum PendingAction {
        case add
        case delete
    }

    private static func pendingRow(
        word: String,
        pos: String,
        translation: String,
        action: PendingAction
    ) -> PendingVocabPresenterState.RowItem {
        let id = UUID()
        let isDelete = action == .delete
        return PendingVocabPresenterState.RowItem(
            id: id,
            row: WordRow.ViewData(
                id: id,
                word: word,
                wordTone: isDelete ? .destructive : .primary,
                isStrikethrough: isDelete,
                partOfSpeech: pos,
                translation: translation,
                bookTitle: nil,
                chapterTitle: nil,
                difficultyTier: nil,
                reviewProgress: nil,
                leadingSystemImage: nil,
                leadingTone: nil,
                trailingLabel: nil,
                trailingTone: nil,
                statusText: nil,
                statusTone: nil
            ),
            actionSystemImage: isDelete ? "arrow.uturn.backward" : "minus.circle",
            actionTone: isDelete ? .destructive : .secondary,
            actionAccessibilityLabel: isDelete ? "復原刪除" : "移除待收錄"
        )
    }
}
#endif
