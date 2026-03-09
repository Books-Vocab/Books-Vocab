import SwiftUI

struct PendingVocabPresenterState {
    struct RowItem: Identifiable {
        let id: UUID
        let row: WordRow.ViewData
        let actionSystemImage: String
        let actionTone: WordRow.ViewData.Tone
    }

    let pendingCount: Int
    let rows: [RowItem]
}

struct PendingVocabPresenter: View {
    @Environment(\.vocabSkin) private var vocabSkin

    let state: PendingVocabPresenterState
    let onRowTapped: (UUID) -> Void
    let onActionTapped: (UUID) -> Void

    var body: some View {
        if state.rows.isEmpty {
            ScrollView {
                VocabEmptyStateCard(
                    title: "沒有待收錄的生詞",
                    systemImage: "character.book.closed",
                    description: "閱讀時點擊的單字會出現在這裡，同步後移入知識庫。"
                )
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                .padding(.top, AppMetrics.spacingMedium)
            }
        } else {
            ScrollView {
                VStack(spacing: 16) {
                    VocabMetricHeroCard(
                        title: "待收錄",
                        description: "同步前的本地收件匣，會保留新增與待刪除動作。",
                        value: "\(state.pendingCount)"
                    )

                    VocabCard(padding: 0) {
                        LazyVStack(spacing: 0) {
                            ForEach(Array(state.rows.enumerated()), id: \.element.id) { index, item in
                                HStack(alignment: .top, spacing: 12) {
                                    WordRow(viewData: item.row)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .contentShape(Rectangle())
                                        .onTapGesture { onRowTapped(item.id) }

                                    VocabAccessoryIconButton(
                                        systemImage: item.actionSystemImage,
                                        tone: resolveTone(item.actionTone),
                                        action: { onActionTapped(item.id) }
                                    )
                                    .padding(.top, 10)
                                }
                                .padding(.horizontal, 18)

                                if index < state.rows.count - 1 {
                                    Divider()
                                        .padding(.leading, 18)
                                }
                            }
                        }
                    }
                }
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                .padding(.top, 10)
                .padding(.bottom, AppShellMetrics.pageBottomPadding / 2)
            }
        }
    }

    private func resolveTone(_ tone: WordRow.ViewData.Tone) -> Color {
        switch tone {
        case .primary:
            return vocabSkin.palette.primaryText
        case .secondary:
            return vocabSkin.palette.secondaryText
        case .tertiary:
            return vocabSkin.palette.tertiaryText
        case .quaternary:
            return vocabSkin.palette.quaternaryText
        case .destructive:
            return vocabSkin.palette.destructive
        case .reviewDue:
            return vocabSkin.tierColor(for: "intermediate")
        }
    }
}
