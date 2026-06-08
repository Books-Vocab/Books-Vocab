#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI
import SwiftData

/// Catalog scenarios for the KG vocabulary list render layer (`KGVocabPresenter`).
///
/// `KGVocabView` itself is driven by a live `@Query` + `@MainActor`
/// `KGVocabCoordinator` with no preview seam, so it cannot be catalogued without
/// seeded SwiftData / network. `KGVocabPresenter` is the stateless render surface
/// that `KGVocabView` constructs and feeds a `State` to — that is what we snapshot.
///
/// `SelectionModeState` is `@MainActor` (`@Observable final class`), so every
/// scenario is built inside a `private struct …Scene: View` body (main-actor
/// isolated). The `Scenario { }` closures only instantiate the scene struct.
enum KGVocabPresenterScenarios {
    static func register(in playbook: Playbook) {
        playbook.addScenarios(of: "KG Vocab Presenter") {
            Scenario("Populated", layout: .fill) {
                KGVocabPresenterScene(kind: .populated)
            }
            Scenario("Banner + Review CTA", layout: .fill) {
                KGVocabPresenterScene(kind: .bannerAndCTA)
            }
            Scenario("Selection Mode Active", layout: .fill) {
                KGVocabPresenterScene(kind: .selecting)
            }
            Scenario("Empty Search", layout: .fill) {
                KGVocabPresenterScene(kind: .emptySearch)
            }
            Scenario("Empty With CTA", layout: .fill) {
                KGVocabPresenterScene(kind: .emptyWithAction)
            }
        }
    }
}

// MARK: - Scene harness (main-actor isolated body)

private struct KGVocabPresenterScene: View {
    enum Kind {
        case populated
        case bannerAndCTA
        case selecting
        case emptySearch
        case emptyWithAction
    }

    let kind: Kind

    @State private var selectedReviewStates: Set<VocabularyReviewState> = []
    @State private var sortOption: KGVocabSortOption = .default
    @State private var selectionState = SelectionModeState()

    var body: some View {
        AppThemeContainer {
            KGVocabPresenter(
                state: makeState(),
                selectedReviewStates: $selectedReviewStates,
                sortOption: $sortOption,
                onDismissBanner: {},
                onRetryBanner: {},
                onRowTapped: { _ in },
                selectionState: configuredSelectionState(),
                onLongPress: { _ in },
                onRefresh: {}
            )
        }
        .environmentObject(AppAppearanceStore.preview)
    }

    // MARK: Selection wiring

    private func configuredSelectionState() -> SelectionModeState {
        if kind == .selecting, !selectionState.isSelecting {
            let ids = Self.rows.map(\.id)
            if let first = ids.first {
                selectionState.enter(with: first)
            }
            if ids.count > 2 {
                selectionState.toggle(ids[2])
            }
        }
        return selectionState
    }

    // MARK: State factory

    private func makeState() -> KGVocabPresenter.State {
        switch kind {
        case .populated:
            return KGVocabPresenter.State(
                banner: nil,
                reviewStateOptions: Self.options,
                rows: Self.rows,
                emptyState: Self.contentEmptyState
            )
        case .bannerAndCTA:
            return KGVocabPresenter.State(
                banner: .init(message: "3 個單字刪除待同步", canDismiss: false, canRetry: true),
                reviewStateOptions: Self.options,
                rows: Self.rows,
                emptyState: Self.contentEmptyState,
                reviewCTA: .init(
                    dueCount: 12,
                    unlearnedCount: 3,
                    onStartDue: {},
                    onStartUnlearned: {},
                    onStartMixed: {}
                )
            )
        case .selecting:
            return KGVocabPresenter.State(
                banner: nil,
                reviewStateOptions: Self.options,
                rows: Self.rows,
                emptyState: Self.contentEmptyState
            )
        case .emptySearch:
            return KGVocabPresenter.State(
                banner: nil,
                reviewStateOptions: Self.options,
                rows: [],
                emptyState: .init(
                    title: "沒有符合的單字",
                    systemImage: "magnifyingglass",
                    description: "試試其他關鍵字，或切換到別的狀態。"
                )
            )
        case .emptyWithAction:
            return KGVocabPresenter.State(
                banner: nil,
                reviewStateOptions: Self.options,
                rows: [],
                emptyState: .init(
                    title: "尚未有任何單字",
                    systemImage: "tray",
                    description: "在閱讀時標記的生詞會自動整理於此。",
                    action: .init(title: "重新整理", systemImage: "arrow.clockwise", handler: {})
                )
            )
        }
    }

    // MARK: Fixtures

    private static let options: [VocabTabOption<VocabularyReviewState>] = [
        .init(id: .unlearned, title: VocabularyReviewState.unlearned.title, count: 3),
        .init(id: .due, title: VocabularyReviewState.due.title, count: 12),
        .init(id: .reviewed, title: VocabularyReviewState.reviewed.title, count: 27),
    ]

    private static let contentEmptyState = KGVocabPresenter.State.EmptyState(
        title: "今天沒有到期卡片",
        systemImage: "checkmark.seal",
        description: "目前沒有需要處理的生字。"
    )

    private static let rows: [KGVocabPresenter.State.RowItem] = {
        func entry(
            _ id: String,
            word: String,
            translation: String,
            pos: String,
            context: String = ""
        ) -> KGVocabPresenter.State.RowItem {
            let e = VocabularyEntry(
                word: word,
                translation: translation,
                context: context,
                partOfSpeech: pos,
                bookTitle: "Sample Book"
            )
            e.id = UUID(uuidString: id)!
            return .init(id: e.id, entry: e)
        }
        return [
            entry("11111111-1111-1111-1111-111111111111",
                  word: "meticulous", translation: "一絲不苟的；非常仔細的", pos: "adj."),
            entry("22222222-2222-2222-2222-222222222222",
                  word: "nuance", translation: "細微差異；語氣層次", pos: "n."),
            entry("33333333-3333-3333-3333-333333333333",
                  word: "serendipity", translation: "機緣巧合", pos: "n.",
                  context: "It was pure serendipity that we met."),
            entry("44444444-4444-4444-4444-444444444444",
                  word: "ephemeral", translation: "短暫的；轉瞬即逝的", pos: "adj."),
        ]
    }()
}
#endif
