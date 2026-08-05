import SwiftUI

enum KGVocabRowSelection {
    static func isHighlighted(rowID: UUID, selectedRowID: UUID?, isSelecting: Bool) -> Bool {
        !isSelecting && selectedRowID == rowID
    }
}

enum KGVocabRowChrome {
    /// 列的 detail highlight 與 hover tint 共用同一個圓度，兩層必須完全重合。
    static let hoverRoundness: CGFloat = AppRoundness.control
}

struct KGVocabPresenter: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    struct State {
        struct Banner {
            let message: String
            let systemImage: String
            let tone: AppBanner.Tone
            let canDismiss: Bool
            let canRetry: Bool
        }

        struct EmptyState {
            let title: String
            let systemImage: String
            let description: String
            let action: AppEmptyStateAction?

            init(title: String, systemImage: String, description: String, action: AppEmptyStateAction? = nil) {
                self.title = title
                self.systemImage = systemImage
                self.description = description
                self.action = action
            }
        }

        struct RowItem: Identifiable {
            let id: UUID
            let entry: VocabularyEntry
        }

        /// 內嵌於 chip+sort 列尾端的「開始複習」CTA payload。
        /// `nil` ⇒ 不顯示 CTA(沒有 due 也沒有 unlearned；或 NotebookListView 內非詳情頁用法)。
        struct ReviewCTA {
            let dueCount: Int
            let unlearnedCount: Int
            let onStartDue: () -> Void
            let onStartUnlearned: () -> Void
            let onStartMixed: () -> Void
        }

        let banner: Banner?
        let roleOptions: [VocabTabOption<VocabularyRoleFilter>]
        let reviewStateOptions: [VocabTabOption<VocabularyReviewState>]
        let rows: [RowItem]
        let emptyState: EmptyState
        let reviewCTA: ReviewCTA?
        let selectedRowID: UUID?

        init(
            banner: Banner?,
            roleOptions: [VocabTabOption<VocabularyRoleFilter>] = VocabularyRoleFilter.allCases.map {
                VocabTabOption(id: $0, title: $0.title, count: 0)
            },
            reviewStateOptions: [VocabTabOption<VocabularyReviewState>],
            rows: [RowItem],
            emptyState: EmptyState,
            reviewCTA: ReviewCTA? = nil,
            selectedRowID: UUID? = nil
        ) {
            self.banner = banner
            self.roleOptions = roleOptions
            self.reviewStateOptions = reviewStateOptions
            self.rows = rows
            self.emptyState = emptyState
            self.reviewCTA = reviewCTA
            self.selectedRowID = selectedRowID
        }
    }

    let state: State
    @Binding var selectedRoleFilter: VocabularyRoleFilter
    @Binding var selectedReviewStates: Set<VocabularyReviewState>
    @Binding var sortOption: KGVocabSortOption
    let onDismissBanner: (() -> Void)?
    let onRetryBanner: (() -> Void)?
    let onRowTapped: (UUID) -> Void
    let selectionState: SelectionModeState
    let onLongPress: (UUID) -> Void
    var onRefresh: (() async -> Void)?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Pinned filter bar — stays visible while scrolling
            VStack(alignment: .leading, spacing: appSkin.spacing.microGap) {
                VocabTabSelector(options: state.roleOptions, selection: $selectedRoleFilter)
                if selectedRoleFilter != .dictionary {
                    VocabFilterChipBar(options: state.reviewStateOptions, selection: $selectedReviewStates)
                }
                HStack(spacing: appSkin.spacing.inlineGap) {
                    Spacer()
                    VocabSortPill(sortOption: $sortOption)
                    if let cta = state.reviewCTA {
                        VocabReviewCTAPill(
                            dueCount: cta.dueCount,
                            unlearnedCount: cta.unlearnedCount,
                            onStartDue: cta.onStartDue,
                            onStartUnlearned: cta.onStartUnlearned,
                            onStartMixed: cta.onStartMixed
                        )
                    }
                }
            }
            .padding(.horizontal, appSkin.metrics.pageHorizontalInset)
            .padding(.top, appSkin.spacing.microGap)
            .padding(.bottom, appSkin.spacing.inlineGap)
            .background(appSkin.palette.pageBackground)

            ScrollView {
            VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
                if let banner = state.banner {
                    AppBanner(
                        message: banner.message,
                        systemImage: banner.systemImage,
                        tone: banner.tone,
                        onRetry: banner.canRetry ? onRetryBanner : nil,
                        onDismiss: banner.canDismiss ? onDismissBanner : nil
                    )
                }


                VocabListCard {
                    EmptyView()
                } content: {
                    Group {
                    if state.rows.isEmpty {
                        VocabEmptyStateContent(
                            title: state.emptyState.title,
                            systemImage: state.emptyState.systemImage,
                            description: state.emptyState.description,
                            guidanceText: state.emptyState.action == nil ? "嘗試切換篩選條件或新增單字" : nil,
                            action: state.emptyState.action
                        )
                        .padding(appSkin.metrics.listRowHorizontalInset)
                        .padding(.vertical, appSkin.metrics.listEmptyStateVerticalInset)
                    } else {
                        LazyVStack(spacing: 0) {
                            ForEach(Array(state.rows.enumerated()), id: \.element.id) { index, item in
                                KGVocabRow(
                                    entry: item.entry,
                                    allowsSelection: item.entry.cardRole == .learning,
                                    isSelecting: selectionState.isSelecting,
                                    isSelected: selectionState.selectedIDs.contains(item.id),
                                    isHighlighted: KGVocabRowSelection.isHighlighted(
                                        rowID: item.id,
                                        selectedRowID: state.selectedRowID,
                                        isSelecting: selectionState.isSelecting
                                    ),
                                    onTap: {
                                        if selectionState.isSelecting {
                                            if item.entry.cardRole == .learning {
                                                selectionState.toggle(item.id)
                                            }
                                        } else {
                                            onRowTapped(item.id)
                                        }
                                    },
                                    onToggleSelection: { selectionState.toggle(item.id) },
                                    onLongPress: {
                                        if !selectionState.isSelecting,
                                           item.entry.cardRole == .learning {
                                            onLongPress(item.id)
                                        }
                                    }
                                )

                                if index < state.rows.count - 1 {
                                    Rectangle()
                                        .fill(appSkin.palette.divider)
                                        .frame(height: AppMetrics.dividerThin)
                                        .padding(.leading, appSkin.metrics.listDividerInset)
                                }
                            }
                        }
                        .animateSpring(selectionState.isSelecting)
                    }
                    }
                }
            }
            .padding(.horizontal, appSkin.metrics.pageHorizontalInset)
            .padding(.top, appSkin.spacing.microGap)
            .padding(.bottom, appSkin.metrics.pageBottomInset)
        }
        .vocabCanvasBackground()
        .platformRefreshable { [onRefresh] in
            await onRefresh?()
        }
        .animateSpring(state.banner == nil)
        } // end outer VStack
        .enableInjection()
    }
}

/// 單字列 — 抽出為獨立 View，使 SwiftUI diff 工作量隨可見 row 數，而非全資料集數量。
///
/// 設計重點：
/// 1. 接受 minimal props（`isSelecting`/`isSelected` 兩個 Bool），不再傳整個 `SelectionModeState` observable，
///    避免 list 中每個 row 都訂閱 selection state 變動而觸發重繪。
/// 2. 不在 row 內部掛 `.animateSpring(selectionState.isSelecting)`，500+ rows 時可省下 500+ 個 animation observer。
///    動畫由父層容器（`LazyVStack`）統一驅動。
struct KGVocabRow: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore

    let entry: VocabularyEntry
    let allowsSelection: Bool
    let isSelecting: Bool
    let isSelected: Bool
    let isHighlighted: Bool
    let onTap: () -> Void
    let onToggleSelection: () -> Void
    let onLongPress: () -> Void

    var body: some View {
        let reviewNow = reviewSettingsStore.settings.reviewReferenceDate()
        HStack(spacing: appSkin.spacing.inlineGap) {
            if isSelecting && allowsSelection {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .font(appSkin.typography.iconMedium)
                    .foregroundStyle(
                        isSelected
                            ? appSkin.palette.accent
                            : appSkin.palette.quaternaryText
                    )
                    .onTapGesture(perform: onToggleSelection)
                    .transition(.selectionReveal)
            }

            WordRow(viewData: entry.wordRowViewData(
                showsReviewState: false,
                showsSourceContext: false,
                showsDifficultyTier: false,
                showsReviewProgress: true,
                now: reviewNow
            ))
                .contentShape(Rectangle())
                .onTapGesture(perform: onTap)
                .onLongPressGesture(perform: onLongPress)
        }
        .padding(.horizontal, appSkin.metrics.listRowHorizontalInset)
        .padding(.vertical, AppSpacing.s1)
        .background {
            if isHighlighted {
                AppRoundedRect(roundness: KGVocabRowChrome.hoverRoundness)
                    .fill(appSkin.palette.accent.opacity(0.08))
            }
        }
        .appHoverRowTint(roundness: KGVocabRowChrome.hoverRoundness)
        .padding(.horizontal, AppSpacing.s1)
        .accessibilityIdentifier("vocab.row.\(entry.word)")
        .transition(.listSwap)
        .enableInjection()
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
        banner: .init(
            message: "2 個單字刪除待同步",
            systemImage: "exclamationmark.triangle.fill",
            tone: .warning,
            canDismiss: false,
            canRetry: true
        ),
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
            selectedRoleFilter: .constant(.all),
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
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("KG List / Empty Search") {
    AppThemeContainer {
        KGVocabPresenter(
            state: KGVocabPresenterPreviewData.emptyState,
            selectedRoleFilter: .constant(.all),
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
    .environmentObject(AppAppearanceStore.preview)
}
