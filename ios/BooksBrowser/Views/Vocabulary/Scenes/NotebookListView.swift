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
    @Environment(\.horizontalSizeClass) private var sizeClass
    @Environment(\.toastCoordinator) private var toastCoordinator
    @State private var coordinator = NotebookListCoordinator()
    @State private var showLoginSheet = false

    init() {
        let knowledgePredicate = #Predicate<VocabularyEntry> {
            $0.syncStatus == 1 &&
            $0.actionType != "delete" &&
            $0.isArchived == false
        }
        _allEntries = Query(filter: knowledgePredicate, sort: \.dateAdded, order: .reverse)
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
    @State private var isEditingDetailEntry = false

    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }

    private var sortOption: NotebookSortOption {
        NotebookSortOption(rawValue: sortOptionRaw) ?? .manual
    }

    var body: some View {
        let stats = NotebookStatsCalculator.compute(allEntries, pendingEntries: pendingEntries)
        let (filteredDueEntries, filteredUnlearnedEntries) = NotebookStatsCalculator.filtered(allEntries, filter: reviewFilter)
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
                    let hasReview = totalDueCount > 0 || totalUnlearnedCount > 0
                    let hasBothTypes = filteredDueEntries.count > 0 && filteredUnlearnedEntries.count > 0
                    let totalReview = filteredDueEntries.count + filteredUnlearnedEntries.count

                    HStack(spacing: AppSpacing.s2) {
                        if hasReview {
                            Text("今日複習".localized)
                                .font(skin.typography.sectionTitle)
                                .foregroundStyle(skin.palette.primaryText)
                        }

                        Spacer(minLength: 8)

                        // CTA pill — 三模式 menu / 單模式 button,inline VocabReviewCTAPill 邏輯
                        // 以套用統一 NotebookHeaderPillLabel 規格(高度與 tool pill 對齊)。
                        if hasReview {
                            if hasBothTypes {
                                Menu {
                                    Button {
                                        startReview(with: filteredDueEntries + filteredUnlearnedEntries)
                                    } label: {
                                        Label(L10n.format("全部複習（%@）", "\(totalReview)"), systemImage: "rectangle.stack")
                                    }
                                    Divider()
                                    Button {
                                        startReview(with: filteredDueEntries)
                                    } label: {
                                        Label(L10n.format("到期複習（%@）", "\(filteredDueEntries.count)"), systemImage: "clock.badge")
                                    }
                                    Button {
                                        startReview(with: filteredUnlearnedEntries)
                                    } label: {
                                        Label(L10n.format("未學複習（%@）", "\(filteredUnlearnedEntries.count)"), systemImage: "sparkles")
                                    }
                                } label: {
                                    NotebookHeaderPillLabel(
                                        fillColor: skin.palette.brandHero,
                                        foregroundColor: AppColors.onBrandHero
                                    ) {
                                        HStack(spacing: AppSpacing.microGap) {
                                            Image(systemName: "play.fill")
                                            Text("\(totalReview)").monospacedDigit()
                                        }
                                    }
                                }
                                .accessibilityLabel(L10n.format("開始複習，共 %@ 張", "\(totalReview)"))
                            } else if filteredDueEntries.count > 0 {
                                Button {
                                    startReview(with: filteredDueEntries)
                                } label: {
                                    NotebookHeaderPillLabel(
                                        fillColor: skin.palette.brandHero,
                                        foregroundColor: AppColors.onBrandHero
                                    ) {
                                        HStack(spacing: AppSpacing.microGap) {
                                            Image(systemName: "clock.badge")
                                            Text("\(filteredDueEntries.count)").monospacedDigit()
                                        }
                                    }
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel(L10n.format("開始到期複習，%@ 張", "\(filteredDueEntries.count)"))
                            } else if filteredUnlearnedEntries.count > 0 {
                                Button {
                                    startReview(with: filteredUnlearnedEntries)
                                } label: {
                                    NotebookHeaderPillLabel(
                                        fillColor: skin.palette.brandHero,
                                        foregroundColor: AppColors.onBrandHero
                                    ) {
                                        HStack(spacing: AppSpacing.microGap) {
                                            Image(systemName: "sparkles")
                                            Text("\(filteredUnlearnedEntries.count)").monospacedDigit()
                                        }
                                    }
                                }
                                .buttonStyle(.plain)
                                .accessibilityLabel(L10n.format("開始未學複習，%@ 張", "\(filteredUnlearnedEntries.count)"))
                            }
                        }

                        if notebooks.count >= 2 {
                            Button {
                                showFilterSheet = true
                            } label: {
                                NotebookHeaderPillLabel(
                                    fillColor: skin.palette.buttonIdleFill,
                                    foregroundColor: reviewFilter.isFiltered ? skin.palette.accent : skin.palette.secondaryText
                                ) {
                                    Image(systemName: reviewFilter.isFiltered
                                        ? "line.3.horizontal.decrease.circle.fill"
                                        : "line.3.horizontal.decrease.circle")
                                }
                            }
                            .buttonStyle(.plain)
                            .accessibilityLabel("篩選單字本".localized)
                        }

                        Button {
                            showCreateSheet = true
                        } label: {
                            NotebookHeaderPillLabel(
                                fillColor: skin.palette.buttonIdleFill,
                                foregroundColor: skin.palette.secondaryText
                            ) {
                                Image(systemName: "plus")
                            }
                        }
                        .buttonStyle(.plain)
                        .disabled(!authManager.isLoggedIn)
                        .accessibilityLabel("新增單字本".localized)
                    }
                    .padding(.horizontal, AppSpacing.s3)
                    .padding(.vertical, AppSpacing.s1)
                    .background(
                        RoundedRectangle(cornerRadius: AppRadius.lg, style: .continuous)
                            .fill(skin.palette.mutedFill.opacity(0.5))
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: AppRadius.lg, style: .continuous)
                            .stroke(skin.palette.divider, lineWidth: 1.5)
                    )
                    .padding(.horizontal, editorialHorizontal)

                    // 北極星二:pill cluster ↔ notebook list 之間靠 AppAirDivider
                    // 分區。dividerAirMargin 已全域收緊 32 → 16 (user feedback)。
                    if !notebooks.isEmpty {
                        AppAirDivider()
                            .padding(.horizontal, editorialHorizontal)
                    }

                    if notebooks.isEmpty {
                        emptyState
                    } else {
                        // Editorial row list — 每本 notebook 一條 full-width row,書背隱喻。
                        // 取代舊 grid + hero 分支(grid 在小卡片下擠破,hero 浪費版面)。
                        LazyVStack(spacing: editorialGridSpacing) {
                            ForEach(sortedNotebooks) { notebook in
                                let s = stats[notebook.remoteId] ?? NotebookStats()
                                NavigationLink(value: notebook.remoteId) {
                                    NotebookCard(
                                        data: notebookCardData(for: notebook, stats: s),
                                        style: .grid,
                                        actions: notebookCardActions(for: notebook)
                                    )
                                }
                                .buttonStyle(.plain)
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
                    if let imgPath = appearance.coverImagePath, imgPath != notebook.coverImagePath {
                        notebook.coverImagePath = imgPath
                    } else if appearance.coverImagePath == nil && notebook.coverImagePath != nil {
                        notebook.coverImagePath = nil
                    }
                    Task { @MainActor in
                        await coordinator.updateNotebook(
                            notebook,
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
        .modifier(DetailPresentation(
            detailState: detailState,
            layoutMode: layoutMode,
            allEntries: allEntries,
            currentUserID: authManager.userId,
            isEditingDetailEntry: $isEditingDetailEntry,
            navigationPath: $navigationPath
        ))
        .enableInjection()
    }

    // MARK: - Notebook card builders

    /// 把 `Notebook` model 收斂成 view-only `NotebookCardData`。
    /// 抽出後 grid / hero 兩條分支共用，避免重複的 init 區塊漂移。
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

    // MARK: - Empty State

    @ViewBuilder
    private var emptyState: some View {
        if authManager.isLoggedIn {
            VocabSceneShell(phase: .empty(
                title: "還沒有單字本".localized,
                systemImage: "books.vertical",
                description: "建立第一本，開始整理你的單字".localized,
                action: .init(
                    title: "建立第一本單字本",
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
                action: .init(title: "登入帳號", systemImage: "person.crop.circle", handler: { showLoginSheet = true })
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

// MARK: - Detail Presentation

private struct DetailPresentation: ViewModifier {
    let detailState: DetailRouter
    let layoutMode: LayoutMode
    let allEntries: [VocabularyEntry]
    let currentUserID: String?
    @Binding var isEditingDetailEntry: Bool
    @Binding var navigationPath: NavigationPath

    @AppStorage("kg_detail_panel_width") private var panelWidth: Double = Double(MacDetailPanelMetrics.defaultWidth)
    @State private var dragWidth: CGFloat?
    @State private var containerWidth: CGFloat = 800

    private var effectivePanelWidth: CGFloat {
        let desired = CGFloat(panelWidth)
        let maxAllowed = containerWidth - MacDetailPanelMetrics.leftMinWidth
        return min(desired, max(maxAllowed, MacDetailPanelMetrics.minWidth))
    }

    func body(content: Content) -> some View {
        Group {
            if layoutMode.usesInlineDetail {
                content
                    .safeAreaInset(edge: .trailing, spacing: 0) {
                        if detailState.hasDetail {
                            HStack(spacing: 0) {
                                DraggableDivider(
                                    panelWidth: Binding(
                                        get: { CGFloat(panelWidth) },
                                        set: { panelWidth = Double($0) }
                                    ),
                                    dragWidth: $dragWidth,
                                    containerWidth: containerWidth,
                                    onDoubleClick: {
                                        withAnimation(AppMotion.standardSpring) {
                                            panelWidth = Double(MacDetailPanelMetrics.defaultWidth)
                                        }
                                    }
                                )
                                inlineDetailPanel
                                    .frame(width: dragWidth ?? effectivePanelWidth)
                            }
                            .transition(.drawerReveal)
                        }
                    }
                    .animation(AppMotion.standardSpring, value: detailState.hasDetail)
                    .onGeometryChange(for: CGFloat.self) { geo in
                        geo.size.width
                    } action: { newWidth in
                        containerWidth = newWidth
                    }
                    .onAppear { dragWidth = nil }
                    .onChange(of: navigationPath) { _, path in
                        if path.isEmpty { detailState.dismiss() }
                    }
                    .onChange(of: detailState.selectedEntry?.id) { _, entryID in
                        if entryID == nil { isEditingDetailEntry = false }
                    }
                    .toastSheet(isPresented: Binding(
                        get: { isEditingDetailEntry && detailState.selectedEntry != nil },
                        set: { isEditingDetailEntry = $0 }
                    )) {
                        if let entry = detailState.selectedEntry {
                            WordEditSheet(entry: entry)
                        }
                    }
            } else {
                content
                    .toastSheet(item: Binding(
                        get: { detailState.selectedEntry },
                        set: { if $0 == nil { detailState.dismiss() } }
                    )) { entry in
                        WordDetailSheet(entry: entry, allEntries: detailState.contextEntries)
                            .appSheet(.large)
                    }
                    .platformFullScreenCover(item: Binding(
                        get: { detailState.activeReviewSession },
                        set: { if $0 == nil { detailState.dismiss() } }
                    )) { session in
                        TodayReviewPhaseView(
                            session: session,
                            allEntries: detailState.contextEntries.isEmpty ? allEntries : detailState.contextEntries,
                            currentUserID: currentUserID,
                            onClose: { detailState.dismiss() }
                        )
                        .toastOverlay()
                    }
            }
        }
        .onChange(of: layoutMode) { _, newMode in
            if !newMode.usesInlineDetail {
                detailState.dismiss()
                isEditingDetailEntry = false
            }
        }
    }

    @ViewBuilder
    private var inlineDetailPanel: some View {
        if let session = detailState.activeReviewSession {
            TodayReviewPhaseView(
                session: session,
                allEntries: detailState.contextEntries.isEmpty ? allEntries : detailState.contextEntries,
                currentUserID: currentUserID,
                onClose: { detailState.dismiss() }
            )
        } else if let entry = detailState.selectedEntry {
            VStack(spacing: 0) {
                VocabOverlayHeader(
                    title: entry.word,
                    systemImage: "character.book.closed",
                    onClose: { detailState.dismiss() },
                    trailing: {
                        VocabChromeIconButton(
                            systemImage: "pencil",
                            label: "編輯".localized,
                            action: { isEditingDetailEntry = true }
                        )
                    }
                )
                WordDetailSheet(
                    entry: entry,
                    allEntries: detailState.contextEntries,
                    wrapInNavigation: false,
                    showsInlineChrome: false
                )
            }
        }
    }
}

// MARK: - NotebookHeaderPillLabel

/// 統一的 Header pill 視覺規格 — 給 NotebookListView Today Review action bar
/// 三 pill（CTA / filter / plus）共用,確保高度與 padding 完全一致,僅差別在「填色 + 長度」。
/// 不含 Button — caller 自行用 Button / Menu 包裹,讓 Menu label 場景也能套用。
/// 形狀：Capsule;高度 ≈ 27pt (約原 22pt × 1.2)。
fileprivate struct NotebookHeaderPillLabel<Content: View>: View {
    let fillColor: Color
    let foregroundColor: Color
    @ViewBuilder let content: Content

    var body: some View {
        content
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(foregroundColor)
            .padding(.horizontal, AppSpacing.s2 + 2)   // 10pt
            .padding(.vertical, 7)
            .frame(minWidth: 32)
            .background(Capsule(style: .continuous).fill(fillColor))
    }
}
