//
//  NotebookListView.swift
//  BooksBrowser
//
//  單字本書架 — 生詞庫 tab 的入口頁

import SwiftUI
import SwiftData
import TipKit
import Inject

struct NotebookListView: View {
    @ObserveInjection private var inject
    @Query(filter: #Predicate<Notebook> { !$0.isDeleted }, sort: \Notebook.sortOrder)
    private var notebooks: [Notebook]
    @Query private var allEntries: [VocabularyEntry]
    @Query private var pendingEntries: [VocabularyEntry]
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.appSkin) private var skin
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore
    @State private var coordinator = NotebookListCoordinator()
    @State private var showLoginSheet = false

    init() {
        _allEntries = Query(filter: VocabularyEntry.knowledgeListPredicate(), sort: \.dateAdded, order: .reverse)
        _pendingEntries = Query(filter: #Predicate<VocabularyEntry> { $0.syncStatus != 1 && $0.actionType != "delete" })
    }

    @State private var showCreateSheet = false
    @State private var editingNotebook: Notebook?
    @AppStorage("activeNotebookId") private var activeNotebookId: String = "default"
    @AppStorage(NotebookSortOption.storageKey) private var sortOptionRaw: String = NotebookSortOption.manual.rawValue
    @State private var reviewFilter = NotebookFilter.load()
    @State private var activeReviewSession: TodayReviewSession?
    @State private var notebookToDelete: Notebook?
    @State private var showArchiveList = false
    @State private var showFilterSheet = false
    @State private var navigationPath = NavigationPath()
    @State private var detailState = DetailRouter()

    private var sortOption: NotebookSortOption {
        NotebookSortOption(rawValue: sortOptionRaw) ?? .manual
    }

    var body: some View {
        let reviewNow = reviewSettingsStore.settings.reviewReferenceDate()
        let stats = NotebookStatsCalculator.compute(
            allEntries,
            pendingEntries: pendingEntries,
            now: reviewNow
        )
        // The filter pill (to change/clear reviewFilter) only renders with ≥2
        // notebooks. If a user filtered then deleted notebooks down to <2, the
        // persisted filter must NOT keep silently hiding entries with no UI to
        // clear it — apply an unfiltered view while keeping reviewFilter intact
        // (it re-applies once they have ≥2 notebooks again).
        let effectiveFilter = notebooks.count >= 2 ? reviewFilter : NotebookFilter()
        let (filteredDueEntries, filteredUnlearnedEntries) = NotebookStatsCalculator.filtered(
            allEntries,
            filter: effectiveFilter,
            now: reviewNow
        )
        let totalDueCount = stats.values.reduce(0) { $0 + $1.dueCount }
        let totalUnlearnedCount = stats.values.reduce(0) { $0 + $1.unlearnedCount }
        let sortedNotebooks = sortOption.sort(notebooks, stats: stats)

        // Editorial tight overrides — 全 app token (`pageHorizontalPadding = s5 = 32pt` /
        // `sectionSpacing = s6 = 48pt` / `sectionGap = 14` / `pageTopInset = 16`) 對
        // Notebooks editorial 太鬆。本地降到 editorial 緊版,不動共用 token。
        let editorialHorizontal: CGFloat = AppSpacing.s3   // 12pt (was 32pt)
        let editorialSectionGap: CGFloat = AppSpacing.s1   // 4pt  (was 8pt — user feedback 緊湊)
        let editorialGridSpacing: CGFloat = AppSpacing.s1  // 4pt  (was 8pt — 卡片之間更貼)
        let editorialTopInset: CGFloat = AppSpacing.zero   // 0    (was 4pt — 頂部不留 inset)

        NavigationStack(path: $navigationPath) {
            ScrollView {
                VStack(spacing: editorialSectionGap) {
                    if let message = coordinator.reconcileError {
                        reconcileErrorBanner(message: message)
                            .padding(.horizontal, editorialHorizontal)
                            .transition(.statusRowReveal)
                    }

                    if !pendingEntries.isEmpty {
                        TipView(SyncPendingTip())
                            .padding(.horizontal, editorialHorizontal)
                    }

                    // D4 — Today Review action bar：title + 三 pill 包進 mutedFill capsule 容器,
                    // 容器 1pt cardBorder 微粗淡 hairline 框、灰填底比框線更淡。
                    // 三 pill (CTA / filter / plus) 統一規格走 NotebookHeaderPillLabel,
                    // 差別僅在「長度 + 填色」— user feedback iteration。
                    NotebookReviewActionBar(
                        dueCount: filteredDueEntries.count,
                        unlearnedCount: filteredUnlearnedEntries.count,
                        hasReviewItems: totalDueCount > 0 || totalUnlearnedCount > 0,
                        notebookCount: notebooks.count,
                        isFiltered: reviewFilter.isFiltered,
                        canCreate: authManager.isLoggedIn,
                        onReviewAll: { startReview(with: filteredDueEntries + filteredUnlearnedEntries) },
                        onReviewDue: { startReview(with: filteredDueEntries) },
                        onReviewUnlearned: { startReview(with: filteredUnlearnedEntries) },
                        onFilter: { showFilterSheet = true },
                        onCreate: { showCreateSheet = true }
                    )
                    .padding(.horizontal, editorialHorizontal)

                    // 北極星二:pill cluster ↔ notebook list 之間靠 AppAirDivider
                    // 分區。dividerAirMargin 已全域收緊 32 → 16 (user feedback)。
                    if !notebooks.isEmpty {
                        AppAirDivider()
                            .padding(.horizontal, editorialHorizontal)
                    }

                    if notebooks.isEmpty && !coordinator.hasLoadedOnce && authManager.isLoggedIn {
                        // 首次 reconcile 完成前不顯示 empty state — 否則 logged-in users
                        // 啟動瞬間會閃過「還沒有單字本」誤導 copy。鏡像 PR #603 Podcast 修法。
                        loadingPlaceholder
                    } else if notebooks.isEmpty {
                        emptyState
                    } else {
                        // Editorial row list — 每本 notebook 一條 full-width row,書背隱喻。
                        // 取代舊 grid + hero 分支(grid 在小卡片下擠破,hero 浪費版面)。
                        LazyVStack(spacing: editorialGridSpacing) {
                            ForEach(sortedNotebooks) { notebook in
                                let s = stats[notebook.remoteId] ?? NotebookStats()
                                notebookActivationSurface(for: notebook) {
                                    NotebookCard(
                                        data: notebookCardData(for: notebook, stats: s),
                                        style: .grid,
                                        actions: notebookCardActions(for: notebook)
                                    )
                                }
                                .transition(.listSwap)
                            }
                        }
                        .padding(.horizontal, editorialHorizontal)
                    }
                }
                .padding(.top, editorialTopInset)
            }
            .background(skin.palette.pageBackground)
            .navigationTitle("單字本".localized)
            .largeNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    sortMenu
                        .disabled(notebooks.isEmpty)
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showArchiveList = true
                    } label: {
                        Image(systemName: "archivebox")
                    }
                    .accessibilityLabel(L10n.string("notebook.toolbar.archive"))
                }
            }
            .navigationDestination(for: String.self) { notebookId in
                VocabularyListView(notebookId: notebookId)
            }
            .toastSheet(isPresented: $showCreateSheet) {
                NotebookEditSheet(mode: .create) { appearance in
                    Task { @MainActor in
                        await coordinator.createNotebook(
                            name: appearance.name,
                            color: appearance.color,
                            coverPattern: appearance.coverPattern,
                            modelContext: modelContext,
                            kgService: kgService,
                            toastCoordinator: toastCoordinator
                        )
                    }
                }
            }
            .toastSheet(item: $editingNotebook) { notebook in
                NotebookEditSheet(
                    mode: .edit(
                        name: notebook.name,
                        color: notebook.color,
                        coverPattern: notebook.coverPattern,
                        coverImagePath: notebook.coverImagePath
                    )
                ) { appearance in
                    // coverImagePath 的落地 + 舊圖刪除延到 updateNotebook API 成功後，
                    // 由 coordinator 統一處理（全有或全無），避免 API 失敗時「新封面 +
                    // server 舊欄位」drift 且舊封面回不去（track-23）。
                    Task { @MainActor in
                        await coordinator.updateNotebook(
                            notebook,
                            name: appearance.name,
                            color: appearance.color,
                            coverPattern: appearance.coverPattern,
                            stagedCoverImagePath: appearance.coverImagePath,
                            originalCoverImagePath: appearance.originalCoverImagePath,
                            modelContext: modelContext,
                            kgService: kgService,
                            toastCoordinator: toastCoordinator
                        )
                    }
                }
            }
            .onChange(of: activeReviewSession) { _, session in
                if let session {
                    detailState.showReview(session, allEntries: allEntries)
                    activeReviewSession = nil
                }
            }
            .toastSheet(isPresented: $showArchiveList) {
                ArchivedVocabSheet()
            }
            .toastSheet(isPresented: $showFilterSheet) {
                NotebookFilterPickerSheet(
                    filter: $reviewFilter,
                    notebooks: notebooks.filter { !$0.isDeleted }
                )
            }
            .toastSheet(item: $coordinator.exportURL) { url in
                PlatformShareView(url: url)
            }
            .task(id: authManager.isLoggedIn) {
                await coordinator.reconcileNotebooks(
                    authManager: authManager,
                    currentNotebooks: notebooks,
                    allEntries: allEntries,
                    modelContext: modelContext,
                    kgService: kgService
                )
            }
            .confirmationDialog(
                "確定要刪除此單字本？".localized,
                isPresented: Binding(
                    get: { notebookToDelete != nil },
                    set: { if !$0 { notebookToDelete = nil } }
                ),
                titleVisibility: .visible
            ) {
                Button("刪除".localized, role: .destructive) {
                    if let notebook = notebookToDelete {
                        Task { @MainActor in
                            await coordinator.deleteNotebook(
                                notebook,
                                isActive: activeNotebookId == notebook.remoteId,
                                availableNotebooks: notebooks,
                                allEntries: allEntries,
                                modelContext: modelContext,
                                kgService: kgService,
                                toastCoordinator: toastCoordinator,
                                setActiveNotebook: { setActiveNotebook($0) }
                            )
                        }
                        notebookToDelete = nil
                    }
                }
            } message: {
                Text("此單字本及所有單字將被永久刪除，無法復原。".localized)
            }
        }
        .environment(\.detailRouter, detailState)
        .modifier(NotebookDetailPresentation(
            detailState: detailState,
            allEntries: allEntries,
            currentUserID: authManager.userId
        ))
        // 新增單字本 ⌘N(Mac menu)— 未登入不 publish → menu 自動 disable(對應 view 內 .disabled(!isLoggedIn))。
        .focusedSceneValue(
            \.newNotebook,
            authManager.isLoggedIn ? NewNotebookAction { showCreateSheet = true } : nil
        )
        // 開始今日複習 ⌘⏎(Mac menu)— 預設「全部」模式;無可複習項不 publish → menu disable。
        .focusedSceneValue(
            \.startReview,
            (filteredDueEntries + filteredUnlearnedEntries).isEmpty
                ? nil
                : StartReviewAction { startReview(with: filteredDueEntries + filteredUnlearnedEntries) }
        )
        .enableInjection()
    }

    // MARK: - Notebook card builders

    /// 把 `Notebook` model 收斂成 view-only `NotebookCardData`，
    /// 隔離 model → view 的對應，避免 init 區塊內聯在 list 迴圈裡。
    private func notebookCardData(for notebook: Notebook, stats s: NotebookStats) -> NotebookCardData {
        NotebookCardData(
            name: notebook.name,
            color: notebook.color,
            coverPattern: notebook.coverPattern,
            coverImagePath: notebook.coverImagePath,
            cardCount: s.cardCount,
            dueCount: s.dueCount,
            unlearnedCount: s.unlearnedCount,
            reviewedCount: s.reviewedCount,
            pendingCount: s.pendingCount,
            lastActivity: s.lastActivity,
            isActive: notebook.remoteId == activeNotebookId
        )
    }

    private func notebookCardActions(for notebook: Notebook) -> NotebookCardActions {
        NotebookCardActions(
            setActive: { setActiveNotebook(notebook.remoteId) },
            rename: { editingNotebook = notebook },
            editCover: { editingNotebook = notebook },
            export: { format in exportNotebook(notebook, format: format) },
            delete: { notebookToDelete = notebook },
            canDelete: !notebook.isDefault
        )
    }

    @ViewBuilder
    private func notebookActivationSurface<Content: View>(
        for notebook: Notebook,
        @ViewBuilder content: () -> Content
    ) -> some View {
        // 單欄收斂後 notebook row 一律 drill-down：走 NavigationLink(value:) →
        // navigationDestination(for: String.self) push VocabularyListView。
        NavigationLink(value: notebook.remoteId) {
            content()
        }
        .buttonStyle(.plain)
    }

    // MARK: - Sort Menu

    @ViewBuilder
    private var sortMenu: some View {
        Menu {
            Picker(selection: Binding(
                get: { sortOption },
                set: { newValue in
                    withAnimation(AppMotion.standardSpring) {
                        sortOptionRaw = newValue.rawValue
                    }
                }
            )) {
                ForEach(NotebookSortOption.allCases) { option in
                    Label(option.label, systemImage: option.systemImage).tag(option)
                }
            } label: {
                Text("排序方式".localized)
            }
        } label: {
            Image(systemName: "arrow.up.arrow.down")
                .accessibilityLabel("排序".localized)
        }
    }

    // MARK: - Export Menu

    private func exportNotebook(_ notebook: Notebook, format: NotebookExportFormat) {
        let entries = allEntries.filter { $0.notebookId == notebook.remoteId }
        let url: URL?
        switch format {
        case .csv:
            url = VocabularyExporter.exportAsCSV(entries: entries)
        case .json:
            url = VocabularyExporter.exportAsJSON(entries: entries)
        case .anki:
            url = VocabularyExporter.exportAsAnki(entries: entries)
        }
        if let url {
            coordinator.exportURL = url
        } else {
            toastCoordinator.error("匯出失敗".localized)
        }
    }

    // MARK: - Reconcile Error Banner

    /// 同步失敗時的 inline 錯誤橫幅：清單仍顯示本地資料，並提醒可手動重試。
    /// 對齊 `ui_state_matrix.md` 的「partial failure → 明確 inline error」方向，
    /// 不沉默吞掉 fetchNotebooks 錯誤。
    @ViewBuilder
    private func reconcileErrorBanner(message: String) -> some View {
        AppStateMessageCard(
            title: "單字本同步失敗".localized,
            systemImage: "exclamationmark.triangle",
            description: message
        ) {
            Button("重試".localized) {
                Task { @MainActor in
                    await coordinator.reconcileNotebooks(
                        authManager: authManager,
                        currentNotebooks: notebooks,
                        allEntries: allEntries,
                        modelContext: modelContext,
                        kgService: kgService
                    )
                }
            }
            .buttonStyle(.appCompactAction(.primary))
        }
    }

    // MARK: - Loading Placeholder

    /// 首次 reconcile 尚未完成時顯示，避免 logged-in users 啟動瞬間誤看到 empty-state copy。
    /// 鏡像 PR #603 Podcast `.loading` 處理 — `loadingSkeleton` 比裸 spinner 更貼近最終 list 版面。
    @ViewBuilder
    private var loadingPlaceholder: some View {
        VocabSceneShell(phase: .loading(
            title: L10n.string("notebook.list.loading"),
            systemImage: "books.vertical"
        )) {
            EmptyView()
        }
    }

    // MARK: - Empty State

    @ViewBuilder
    private var emptyState: some View {
        if authManager.isLoggedIn {
            VocabSceneShell(phase: .empty(
                title: "還沒有單字本".localized,
                systemImage: "books.vertical",
                description: "建立第一本，開始整理你的單字".localized,
                action: .init(
                    title: "建立第一本單字本".localized,
                    systemImage: "plus.circle.fill",
                    handler: { showCreateSheet = true }
                )
            )) {
                EmptyView()
            }
        } else {
            VocabSceneShell(phase: .empty(
                title: "還沒有單字本".localized,
                systemImage: "books.vertical",
                description: "登入後自動建立預設單字本".localized,
                action: .init(title: "登入帳號".localized, systemImage: "person.crop.circle", handler: { showLoginSheet = true })
            )) {
                EmptyView()
            }
            .sheet(isPresented: $showLoginSheet) {
                LoginSheet()
            }
        }
    }

    // MARK: - Review Helpers

    private func startReview(with entries: [VocabularyEntry]) {
        // 空 entries 不再靜默吞掉：交給 TodayReviewPhaseView 落入 .empty 分支，
        // 提供明確回饋（active filter 下 filtered 集合可能為空，但 banner 仍顯示）。
        activeReviewSession = TodayReviewSession(entries: entries)
    }

    private func setActiveNotebook(_ id: String) {
        activeNotebookId = id
    }
}
