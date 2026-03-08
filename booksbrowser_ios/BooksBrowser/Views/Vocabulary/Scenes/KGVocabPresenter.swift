import SwiftUI

struct KGVocabPresenter: View {
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
            VStack(alignment: .leading, spacing: AppMetrics.spacingLarge) {
                if let banner = state.banner {
                    ErrorBannerView(
                        message: banner.message,
                        onDismiss: banner.canDismiss ? onDismissBanner : nil,
                        onRetry: banner.canRetry ? onRetryBanner : nil
                    )
                }

                VocabCard(padding: 0) {
                    VStack(alignment: .leading, spacing: 0) {
                        VStack(alignment: .leading, spacing: 10) {
                            VocabTabSelector(options: state.reviewStateOptions, selection: $selectedReviewState)
                        }
                        .padding(.horizontal, 16)
                        .padding(.top, 14)
                        .padding(.bottom, 12)

                        Divider()
                            .padding(.horizontal, 16)

                        if state.rows.isEmpty {
                            VocabEmptyStateContent(
                                title: state.emptyState.title,
                                systemImage: state.emptyState.systemImage,
                                description: state.emptyState.description
                            )
                            .padding(16)
                            .padding(.vertical, 4)
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
                                        .padding(.horizontal, 16)

                                    if index < state.rows.count - 1 {
                                        Divider()
                                            .padding(.leading, 16)
                                    }
                                }
                            }
                        }
                    }
                }
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppMetrics.spacingLarge)
            .padding(.bottom, 120)
        }
        .vocabCanvasBackground()
    }
}
