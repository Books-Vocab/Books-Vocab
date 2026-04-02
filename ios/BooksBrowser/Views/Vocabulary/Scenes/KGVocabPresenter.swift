import SwiftUI

struct KGVocabPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    struct State {
        struct Banner {
            let message: String
            let canDismiss: Bool
            let canRetry: Bool
        }

        struct EmptyState {
            let title: String
            let systemImage: String
            let description: String
        }

        struct RowItem: Identifiable {
            let id: UUID
            let entry: VocabularyEntry
        }

        let banner: Banner?
        let reviewStateOptions: [VocabTabOption<VocabularyReviewState>]
        let rows: [RowItem]
        let emptyState: EmptyState
    }

    let state: State
    @Binding var selectedReviewStates: Set<VocabularyReviewState>
    @Binding var sortOption: KGVocabSortOption
    let onDismissBanner: (() -> Void)?
    let onRetryBanner: (() -> Void)?
    let onRowTapped: (UUID) -> Void
    let selectionState: SelectionModeState
    let onLongPress: (UUID) -> Void
    var onRefresh: (() async -> Void)?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                if let banner = state.banner {
                    AppBanner(
                        message: banner.message,
                        systemImage: "exclamationmark.triangle.fill",
                        onRetry: banner.canRetry ? onRetryBanner : nil,
                        onDismiss: banner.canDismiss ? onDismissBanner : nil
                    )
                }


                VocabListCard {
                    VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                        VocabFilterChipBar(options: state.reviewStateOptions, selection: $selectedReviewStates)
                        HStack {
                            Spacer()
                            VocabSortPill(sortOption: $sortOption)
                        }
                    }
                } content: {
                    Group {
                    if state.rows.isEmpty {
                        VocabEmptyStateContent(
                            title: state.emptyState.title,
                            systemImage: state.emptyState.systemImage,
                            description: state.emptyState.description,
                            guidanceText: "嘗試切換篩選條件或新增單字"
                        )
                        .padding(vocabSkin.metrics.listRowHorizontalInset)
                        .padding(.vertical, vocabSkin.metrics.listEmptyStateVerticalInset)
                    } else {
                        LazyVStack(spacing: 0) {
                            ForEach(Array(state.rows.enumerated()), id: \.element.id) { index, item in
                                HStack(spacing: vocabSkin.spacing.inlineGap) {
                                    if selectionState.isSelecting {
                                        Image(systemName: selectionState.selectedIDs.contains(item.id) ? "checkmark.circle.fill" : "circle")
                                            .font(vocabSkin.typography.iconMedium)
                                            .foregroundStyle(
                                                selectionState.selectedIDs.contains(item.id)
                                                    ? vocabSkin.palette.accent
                                                    : vocabSkin.palette.quaternaryText
                                            )
                                            .onTapGesture { selectionState.toggle(item.id) }
                                            .transition(.selectionReveal)
                                    }

                                    WordRow(viewData: item.entry.wordRowViewData(
                                        showsReviewState: false,
                                        showsSourceContext: false,
                                        showsDifficultyTier: false,
                                        showsReviewProgress: true
                                    ))
                                        .contentShape(Rectangle())
                                        .onTapGesture {
                                            if selectionState.isSelecting {
                                                selectionState.toggle(item.id)
                                            } else {
                                                onRowTapped(item.id)
                                            }
                                        }
                                        .onLongPressGesture {
                                            if !selectionState.isSelecting {
                                                onLongPress(item.id)
                                            }
                                        }
                                }
                                .padding(.horizontal, vocabSkin.metrics.listRowHorizontalInset)
                                .animateSpring(selectionState.isSelecting)
                                .transition(.asymmetric(insertion: .listInsert, removal: .listRemove))

                                if index < state.rows.count - 1 {
                                    Rectangle()
                                        .fill(vocabSkin.palette.divider)
                                        .frame(height: AppMetrics.dividerThin)
                                        .padding(.leading, vocabSkin.metrics.listDividerInset)
                                }
                            }
                        }
                    }
                    }
                }
            }
            .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
            .padding(.top, vocabSkin.metrics.pageTopInset)
            .padding(.bottom, vocabSkin.metrics.pageBottomInset)
        }
        .vocabCanvasBackground()
        .platformRefreshable { [onRefresh] in
            await onRefresh?()
        }
        .animateSpring(state.banner == nil)
    }
}

private enum KGVocabPresenterPreviewData {
    static let options = VocabularyReviewState.allCases.map {
        VocabTabOption(id: $0, title: $0.title, count: count(for: $0))
    }

    static let rows: [KGVocabPresenter.State.RowItem] = {
        let e1 = VocabularyEntry(
            word: "meticulous",
            translation: "一絲不苟的；非常仔細的",
            context: "",
            bookTitle: "Sample"
        )
        e1.id = UUID(uuidString: "11111111-1111-1111-1111-111111111111")!
        e1.partOfSpeech = "adj."
        let e2 = VocabularyEntry(
            word: "nuance",
            translation: "細微差異；語氣層次",
            context: "",
            bookTitle: "Sample"
        )
        e2.id = UUID(uuidString: "22222222-2222-2222-2222-222222222222")!
        e2.partOfSpeech = "n."
        return [
            .init(id: e1.id, entry: e1),
            .init(id: e2.id, entry: e2)
        ]
    }()

    static let populatedState = KGVocabPresenter.State(
        banner: .init(message: "2 個單字刪除待同步", canDismiss: false, canRetry: true),
        reviewStateOptions: options,
        rows: rows,
        emptyState: .init(
            title: "今天沒有到期卡片".localized,
            systemImage: "checkmark.seal",
            description: "目前沒有需要處理的生字。".localized
        )
    )

    static let emptyState = KGVocabPresenter.State(
        banner: nil,
        reviewStateOptions: options,
        rows: [],
        emptyState: .init(
            title: "沒有符合的單字".localized,
            systemImage: "magnifyingglass",
            description: "試試其他關鍵字，或切換到別的狀態。".localized
        )
    )

    private static func count(for state: VocabularyReviewState) -> Int {
        switch state {
        case .unlearned:
            return 3
        case .due:
            return 12
        case .reviewed:
            return 27
        }
    }
}

#Preview("KG List / Populated") {
    AppThemeContainer {
        KGVocabPresenter(
            state: KGVocabPresenterPreviewData.populatedState,
            selectedReviewStates: .constant([]),
            sortOption: .constant(.default),
            onDismissBanner: {},
            onRetryBanner: {},
            onRowTapped: { _ in },
            selectionState: SelectionModeState(),
            onLongPress: { _ in },
            onRefresh: {}
        )
    }
}

#Preview("KG List / Empty Search") {
    AppThemeContainer {
        KGVocabPresenter(
            state: KGVocabPresenterPreviewData.emptyState,
            selectedReviewStates: .constant([.reviewed]),
            sortOption: .constant(.alphabetical),
            onDismissBanner: nil,
            onRetryBanner: nil,
            onRowTapped: { _ in },
            selectionState: SelectionModeState(),
            onLongPress: { _ in },
            onRefresh: {}
        )
    }
}
