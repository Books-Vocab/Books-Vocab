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
    let knowledgeCount: Int
    let dueCount: Int
}

struct PendingVocabPresenter: View {
    @Environment(\.appSkin) private var appSkin

    let state: PendingVocabPresenterState
    let onRowTapped: (UUID) -> Void
    let onActionTapped: (UUID) -> Void
    let onSwitchToKnowledge: () -> Void

    var body: some View {
        if state.rows.isEmpty {
            VocabSceneShell(phase: .empty(
                title: "沒有待收錄的生詞".localized,
                systemImage: "character.book.closed",
                description: state.knowledgeCount > 0
                    ? (state.dueCount > 0
                        ? L10n.format("已收錄 %d 個單字，其中 %d 個待複習。", state.knowledgeCount, state.dueCount)
                        : L10n.format("已收錄 %d 個單字，去複習鞏固記憶吧。", state.knowledgeCount))
                    : "閱讀時點擊的單字會出現在這裡，同步後即為已收錄。".localized
            )) {
                EmptyView()
            }
            .transition(.listItemFade)
        } else {
            ScrollView {
                VStack(spacing: appSkin.metrics.heroSectionSpacing) {
                    VocabMetricHeroCard(
                        title: "待收錄".localized,
                        description: "同步前的本地收件匣，會保留新增與待刪除動作。".localized,
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
                                    .padding(.top, appSkin.metrics.accessoryTopOffset)
                                }
                                .padding(.horizontal, appSkin.spacing.cardPadding)
                                .transition(.listItemFade)

                                if index < state.rows.count - 1 {
                                    Divider()
                                        .padding(.leading, appSkin.spacing.cardPadding)
                                }
                            }
                        }
                        .animateSpring(state.rows.count)
                    }
                }
                .padding(.horizontal, appSkin.metrics.pageHorizontalInset)
                .padding(.top, appSkin.metrics.pageTopInset)
                .padding(.bottom, AppShellMetrics.pageBottomPadding / 2)
            }
        }
    }

    private func resolveTone(_ tone: WordRow.ViewData.Tone) -> Color {
        switch tone {
        case .primary:
            return appSkin.palette.primaryText
        case .secondary:
            return appSkin.palette.secondaryText
        case .tertiary:
            return appSkin.palette.tertiaryText
        case .quaternary:
            return appSkin.palette.quaternaryText
        case .destructive:
            return appSkin.palette.destructive
        case .reviewDue:
            return appSkin.palette.warning
        }
    }
}
