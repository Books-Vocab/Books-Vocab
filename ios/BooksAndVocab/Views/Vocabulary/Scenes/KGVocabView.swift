//
//  KGVocabView.swift
//  Books & Vocab
//
//  Typography-driven knowledge base browser.
//  Clean white cards, generous spacing, ghost buttons, typography-driven hierarchy.
//

import SwiftUI
import SwiftData
import os

struct KGVocabView: View {
    @ObserveInjection private var inject
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.appSkin) private var appSkin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore
    @Environment(\.catalogTaskPolicy) private var catalogTaskPolicy
    @Binding var searchText: String

    let notebookId: String
    /// macOS: word detail 由父頁的 split panel 顯示，透過此 callback 傳出
    var onEntrySelected: ((VocabularyEntry) -> Void)?
    /// 詳情頁「開始複習」CTA callback — 由父層 (VocabularyListView+State) 注入。
    /// `nil` ⇒ chip+sort 列尾端不顯示 CTA pill (e.g. macOS split detail pane)。
    var onStartReview: (([VocabularyEntry]) -> Void)?

    @Query private var syncedEntries: [VocabularyEntry]
    @Environment(\.authManager) private var authManager

    @State private var coordinator = KGVocabCoordinator()
    @State private var query: VocabularyLibraryQuery
    @State private var selectionState = SelectionModeState()
    @State private var selectedRowID: UUID?
    @State private var loginGate = LoginGateState()
    @Query private var pendingDeletes: [VocabularyEntry]

    init(
        searchText: Binding<String>,
        notebookId: String = "default",
        onEntrySelected: ((VocabularyEntry) -> Void)? = nil,
        onStartReview: (([VocabularyEntry]) -> Void)? = nil,
        initialReviewStates: Set<VocabularyReviewState> = [],
        initialSort: KGVocabSortOption = .default
    ) {
        self._searchText = searchText
        self.notebookId = notebookId
        self.onEntrySelected = onEntrySelected
        self.onStartReview = onStartReview
        // Store the values as one query so every projection consumer sees the
        // same progress filter and sort.
        let initialQuery = VocabularyLibraryQuery(
            reviewStates: initialReviewStates,
            sort: initialSort
        )
        self._query = State(initialValue: initialQuery.normalized)
        let nbId = notebookId
        // Notebook-scoped knowledge list. The isArchived guard (inside the shared
        // predicate) keeps archived words out of the KG list and out of
        // WordDetailSheet's link-candidate set (allEntries).
        self._syncedEntries = Query(filter: VocabularyEntry.knowledgeListPredicate(notebookId: nbId))
        let deleteFilter = #Predicate<VocabularyEntry> {
            $0.actionType == "delete" &&
            $0.notebookId == nbId
        }
        self._pendingDeletes = Query(filter: deleteFilter)
    }

    var body: some View {
        let n = reviewSettingsStore.settings.reviewReferenceDate()
        let projectionQuery = query.withSearchText(searchText)
        let projection = VocabularyEntryPresentation.project(
            syncedEntries,
            query: projectionQuery,
            now: n
        )

        VocabSceneShell(phase: buildScenePhase()) {
            contentView(projection: projection)
        }
        // Low-frequency search evidence mark: fires once per (debounced) query
        // change, with the freshly filtered result count from this body eval.
        .onChange(of: searchText) { _, newValue in
            query.searchText = newValue
            // Search changes the visible ID set. Exit selection immediately
            // instead of waiting for a later projection callback, so a stale
            // selected UUID can never be archived from a different query.
            selectionState.exit()
            selectedRowID = nil
            PerfLog.search.mark("search.results.shown", "query=\(newValue) count=\(projection.visibleEntries.count)")
        }
        .animatePhaseChange(coordinator.isLoading)
        .animatePhaseChange(coordinator.errorMessage == nil)
        .onChange(of: coordinator.selectedEntry) { _, entry in
            if let entry, let callback = onEntrySelected {
                callback(entry)
                coordinator.selectedEntry = nil
            }
        }
        .toastSheet(item: Binding(
            get: { onEntrySelected == nil ? coordinator.selectedEntry : nil },
            set: { coordinator.selectedEntry = $0 }
        )) { entry in
            WordDetailSheet(entry: entry, allEntries: syncedEntries)
                .appSheet(.large)
        }
        .task {
            guard catalogTaskPolicy.runsTasks else { return }
            await coordinator.loadInitialData(
                authManager: authManager,
                kgService: kgService,
                modelContext: modelContext
            )
        }
        .enableInjection()
    }

    private func contentView(
        projection: VocabularyLibraryProjection
    ) -> some View {
        let tabOptions = VocabularyReviewState.allCases.map { state in
            VocabTabOption(
                id: state,
                title: state.title,
                count: projection.reviewCount(for: state)
            )
        }
        // Selection and empty state use visible rows; the CTA deliberately uses
        // the scope-wide review queue so search/facet narrowing cannot hide due
        // work that remains actionable.
        let selectableIDs = VocabularyEntryPresentation.selectableIDs(in: projection.visibleEntries)
        let reviewCTA: KGVocabPresenter.State.ReviewCTA? = {
            guard let handler = onStartReview else { return nil }
            let due = projection.reviewQueue.due
            let unlearned = projection.reviewQueue.unlearned
            guard !due.isEmpty || !unlearned.isEmpty else { return nil }
            return .init(
                dueCount: due.count,
                unlearnedCount: unlearned.count,
                onStartDue: { handler(due) },
                onStartUnlearned: { handler(unlearned) },
                onStartMixed: { handler(due + unlearned) }
            )
        }()
        let resolvedEmptyState = KGVocabEmptyState.resolve(projection.emptyStateContext)
        let emptyState = KGVocabPresenter.State.EmptyState(
            title: resolvedEmptyState.title,
            systemImage: resolvedEmptyState.systemImage,
            description: resolvedEmptyState.description,
            action: emptyStateAction(for: projection)
        )

        let state = KGVocabPresenter.State(
            banner: bannerState,
            reviewStateOptions: tabOptions,
            rows: projection.visibleEntries.map {
                KGVocabPresenter.State.RowItem(id: $0.id, entry: $0)
            },
            emptyState: emptyState,
            reviewCTA: reviewCTA,
            selectedRowID: selectedRowID
        )

        return KGVocabPresenter(
            state: state,
            query: $query,
            onDismissBanner: { coordinator.dismissBanner() },
            // 待刪除 banner → 重試刪除；refresh 錯誤 banner → 重試 forceRefresh。
            // 兩者互斥（banner factory 優先序：待刪除 > 錯誤），可否重試由 banner.canRetry 決定顯示。
            onRetryBanner: {
                Task {
                    if pendingDeletes.isEmpty {
                        await coordinator.forceRefresh(
                            kgService: kgService,
                            modelContext: modelContext
                        )
                    } else {
                        await coordinator.retryPendingDeletes(
                            pendingDeletes: pendingDeletes,
                            kgService: kgService,
                            modelContext: modelContext
                        )
                    }
                }
            },
            onRowTapped: { entryID in
                handleRowTap(entryID)
            },
            selectionState: selectionState,
            onLongPress: { id in selectionState.enter(with: id) },
            onRefresh: {
                await coordinator.forceRefresh(
                    kgService: kgService,
                    modelContext: modelContext
                )
            }
        )
        .overlay(alignment: .bottom) {
            if selectionState.isSelecting {
                SelectionToolbar(
                    selectionCount: selectionState.selectionCount,
                    onArchive: { handleBatchArchive() },
                    onDelete: { handleBatchDelete() }
                )
                .transition(.readerPanelReveal)
            }
        }
        .animateSpring(selectionState.isSelecting)
        .onChange(of: query) { _, _ in
            selectionState.exit()
        }
        .onChange(of: selectableIDs.count) { _, newCount in
            selectionState.updateVisibleCount(newCount)
        }
        .onChange(of: projection.visibleEntries.map(\.id)) { _, ids in
            if let selectedRowID, !ids.contains(selectedRowID) {
                self.selectedRowID = nil
            }
        }
        .toolbar {
            if selectionState.isSelecting {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消".localized) { selectionState.exit() }
                }
                ToolbarItem(placement: .primaryAction) {
                    Button(selectionState.isAllSelected ? "取消全選".localized : "全選".localized) {
                        if selectionState.isAllSelected {
                            selectionState.deselectAll()
                        } else {
                            selectionState.selectAll(selectableIDs)
                        }
                    }
                }
            }
        }
        .loginGateSheet($loginGate)
    }

    // MARK: - Computed

    private func buildScenePhase() -> VocabScenePhase {
        if !authManager.isLoggedIn {
            return .empty(
                title: "尚未登入".localized,
                systemImage: "person.crop.circle.badge.exclamationmark",
                description: "登入後，您在閱讀時標記的生詞將會自動整理於此。".localized,
                action: .init(title: "登入帳號".localized, systemImage: "person.crop.circle", handler: { loginGate.presentLogin() })
            )
        } else if coordinator.errorMessage != nil && syncedEntries.isEmpty {
            return .error(
                title: "無法載入單字".localized,
                systemImage: "exclamationmark.triangle",
                description: "請確認網路連線後重試".localized,
                // 使用者按的「重試」是顯式動作，走 forceRefresh —— 與下拉刷新、banner
                // 重試、空狀態 CTA 同一條路。走 loadInitialData 會被歸類為 automatic，
                // 於是「重試成功但沒有變化」時整個畫面靜默無回應。
                retryAction: {
                    Task {
                        await coordinator.forceRefresh(
                            kgService: kgService,
                            modelContext: modelContext
                        )
                    }
                }
            )
        } else if coordinator.isLoading && syncedEntries.isEmpty {
            return .loadingSkeleton()
        } else {
            return .content
        }
    }

    private var bannerState: KGVocabPresenter.State.Banner? {
        return KGVocabBanner.make(
            pendingDeleteCount: pendingDeletes.count,
            error: coordinator.bannerError,
            refreshSuccessMessage: coordinator.refreshSuccessMessage
        )
    }


    /// CTA：僅在「整本 notebook 完全沒卡」時提供 — 觸發強制同步以拉雲端資料。
    /// 搜尋/篩選導致為空時不顯示 CTA（清掉條件即可）。
    private func emptyStateAction(for projection: VocabularyLibraryProjection) -> AppEmptyStateAction? {
        guard syncedEntries.isEmpty,
              projection.effectiveQuery.searchText.isEmpty,
              projection.effectiveQuery.reviewStates.isEmpty,
              authManager.isLoggedIn else {
            return nil
        }
        return AppEmptyStateAction(
            title: "重新整理".localized,
            systemImage: "arrow.clockwise",
            handler: {
                Task {
                    await coordinator.forceRefresh(
                        kgService: kgService,
                        modelContext: modelContext
                    )
                }
            }
        )
    }

    // MARK: - Helpers

    private func handleRowTap(_ entryID: UUID) {
        selectedRowID = entryID
        coordinator.handleRowTap(entryID, syncedEntries: syncedEntries)
    }

    private func handleBatchDelete() {
        coordinator.handleBatchDelete(
            selectionState.selectedIDs,
            syncedEntries: syncedEntries,
            modelContext: modelContext,
            toastCoordinator: toastCoordinator
        )
        selectionState.exit()
    }

    private func handleBatchArchive() {
        let ids = selectionState.selectedIDs
        selectionState.exit()
        Task {
            await coordinator.handleBatchArchive(
                ids,
                syncedEntries: syncedEntries,
                kgService: kgService,
                modelContext: modelContext,
                toastCoordinator: toastCoordinator
            )
        }
    }

}

// MARK: - Preview

#Preview("KGVocab / Default") {
    AppThemeContainer {
        NavigationStack {
            KGVocabView(searchText: .constant(""))
        }
        .modelContainer(for: [VocabularyEntry.self, Notebook.self, ReviewRecord.self], inMemory: true)
    }
    .environmentObject(AppAppearanceStore.preview)
}
