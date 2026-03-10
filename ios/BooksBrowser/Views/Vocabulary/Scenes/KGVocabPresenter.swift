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
            let row: WordRow.ViewData
        }

        let banner: Banner?
        let reviewStateOptions: [VocabTabOption<VocabularyReviewState>]
        let rows: [RowItem]
        let emptyState: EmptyState
    }

    let state: State
    @Binding var selectedReviewState: VocabularyReviewState
    @Binding var sortOption: KGVocabSortOption
    let onDismissBanner: (() -> Void)?
    let onRetryBanner: (() -> Void)?
    let onRowTapped: (UUID) -> Void
    let onDeleteTapped: (UUID) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                if let banner = state.banner {
                    ErrorBannerView(
                        message: banner.message,
                        onDismiss: banner.canDismiss ? onDismissBanner : nil,
                        onRetry: banner.canRetry ? onRetryBanner : nil
                    )
                    .transition(.move(edge: .top).combined(with: .opacity))
                }


                VocabListCard {
                    VStack(alignment: .leading, spacing: 6) {
                        VocabTabSelector(options: state.reviewStateOptions, selection: $selectedReviewState)
                        HStack {
                            Spacer()
                            VocabSortPill(sortOption: $sortOption)
                        }
                    }
                } content: {
                    if state.rows.isEmpty {
                        VocabEmptyStateContent(
                            title: state.emptyState.title,
                            systemImage: state.emptyState.systemImage,
                            description: state.emptyState.description
                        )
                        .padding(vocabSkin.metrics.listRowHorizontalInset)
                        .padding(.vertical, vocabSkin.metrics.listEmptyStateVerticalInset)
                    } else {
                        LazyVStack(spacing: 0) {
                            ForEach(Array(state.rows.enumerated()), id: \.element.id) { index, item in
                                WordRow(viewData: item.row)
                                    .contentShape(Rectangle())
                                    .onTapGesture { onRowTapped(item.id) }
                                    .contextMenu {
                                        Button(role: .destructive) {
                                            onDeleteTapped(item.id)
                                        } label: {
                                            Label("刪除卡片", systemImage: "trash")
                                        }
                                    }
                                    .padding(.horizontal, vocabSkin.metrics.listRowHorizontalInset)

                                if index < state.rows.count - 1 {
                                    Divider()
                                        .padding(.leading, vocabSkin.metrics.listDividerInset)
                                }
                            }
                        }
                        .animation(AppMotion.standardSpring, value: selectedReviewState)
                    }
                }
            }
            .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
            .padding(.top, vocabSkin.metrics.pageTopInset)
            .padding(.bottom, vocabSkin.metrics.pageBottomInset)
        }
        .vocabCanvasBackground()
        .animation(AppMotion.standardSpring, value: state.banner == nil)
    }
}

private enum KGVocabPresenterPreviewData {
    static let options = VocabularyReviewState.allCases.map {
        VocabTabOption(id: $0, title: $0.title, count: count(for: $0))
    }

    static let rows: [KGVocabPresenter.State.RowItem] = [
        .init(
            id: UUID(uuidString: "11111111-1111-1111-1111-111111111111")!,
            row: WordRow.ViewData(
                id: UUID(uuidString: "11111111-1111-1111-1111-111111111111")!,
                word: "meticulous",
                wordTone: .primary,
                isStrikethrough: false,
                partOfSpeech: "adj.",
                translation: "一絲不苟的；非常仔細的",
                bookTitle: nil,
                chapterTitle: nil,
                difficultyTier: nil,
                reviewProgress: .init(
                    statusLabel: "待複習",
                    detailLabel: "18h / 24h",
                    fraction: 0.75,
                    tone: .orange
                ),
                leadingSystemImage: nil,
                leadingTone: nil,
                trailingLabel: nil,
                trailingTone: nil,
                statusText: nil,
                statusTone: nil
            )
        ),
        .init(
            id: UUID(uuidString: "22222222-2222-2222-2222-222222222222")!,
            row: WordRow.ViewData(
                id: UUID(uuidString: "22222222-2222-2222-2222-222222222222")!,
                word: "nuance",
                wordTone: .primary,
                isStrikethrough: false,
                partOfSpeech: "n.",
                translation: "細微差異；語氣層次",
                bookTitle: nil,
                chapterTitle: nil,
                difficultyTier: nil,
                reviewProgress: .init(
                    statusLabel: "已複習",
                    detailLabel: "3d / 7d",
                    fraction: 0.43,
                    tone: .yellow
                ),
                leadingSystemImage: nil,
                leadingTone: nil,
                trailingLabel: nil,
                trailingTone: nil,
                statusText: nil,
                statusTone: nil
            )
        )
    ]

    static let populatedState = KGVocabPresenter.State(
        banner: .init(message: "2 個單字刪除待同步", canDismiss: false, canRetry: true),
        reviewStateOptions: options,
        rows: rows,
        emptyState: .init(
            title: "今天沒有到期卡片",
            systemImage: "checkmark.seal",
            description: "目前沒有需要處理的生字。"
        )
    )

    static let emptyState = KGVocabPresenter.State(
        banner: nil,
        reviewStateOptions: options,
        rows: [],
        emptyState: .init(
            title: "沒有符合的單字",
            systemImage: "magnifyingglass",
            description: "試試其他關鍵字，或切換到別的狀態。"
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
            selectedReviewState: .constant(.due),
            sortOption: .constant(.default),
            onDismissBanner: {},
            onRetryBanner: {},
            onRowTapped: { _ in },
            onDeleteTapped: { _ in }
        )
    }
}

#Preview("KG List / Empty Search") {
    AppThemeContainer {
        KGVocabPresenter(
            state: KGVocabPresenterPreviewData.emptyState,
            selectedReviewState: .constant(.reviewed),
            sortOption: .constant(.alphabetical),
            onDismissBanner: nil,
            onRetryBanner: nil,
            onRowTapped: { _ in },
            onDeleteTapped: { _ in }
        )
    }
}
