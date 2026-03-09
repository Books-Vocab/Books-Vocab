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
                }

                VocabListCard {
                    VStack(alignment: .leading, spacing: vocabSkin.metrics.sectionHeaderGap) {
                        VocabSectionHeader(
                            title: selectedReviewState.title,
                            trailingText: state.rows.isEmpty ? nil : "\(state.rows.count)"
                        )
                        VocabTabSelector(options: state.reviewStateOptions, selection: $selectedReviewState)
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
                    }
                }
            }
            .padding(.horizontal, vocabSkin.metrics.pageHorizontalInset)
            .padding(.top, vocabSkin.metrics.pageTopInset)
            .padding(.bottom, vocabSkin.metrics.pageBottomInset)
        }
        .vocabCanvasBackground()
    }
}
