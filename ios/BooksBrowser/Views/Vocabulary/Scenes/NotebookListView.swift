//
//  NotebookListView.swift
//  BooksBrowser
//
//  單字本書架 — 生詞庫 tab 的入口頁

import SwiftUI
import SwiftData
import TipKit

struct NotebookListView: View {
    @Query(filter: #Predicate<Notebook> { !$0.isDeleted }, sort: \Notebook.sortOrder)
    private var notebooks: [Notebook]
    @Query private var allEntries: [VocabularyEntry]
    @Query private var pendingEntries: [VocabularyEntry]
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.vocabSkin) private var skin
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
    @State private var reviewFilter = NotebookFilter.load()
    @State private var activeReviewSession: TodayReviewSession?
    @State private var notebookToDelete: Notebook?
    @State private var showArchiveList = false
    @State private var navigationPath = NavigationPath()
    @State private var detailState = DetailRouter()
    @State private var isEditingDetailEntry = false

    private var layoutMode: LayoutMode { LayoutMode(horizontalSizeClass: sizeClass) }

    var body: some View {
        let stats = Self.computeNotebookStats(allEntries, pendingEntries: pendingEntries)
        let (filteredDueEntries, filteredUnlearnedEntries) = Self.computeFilteredEntries(allEntries, filter: reviewFilter)
        let totalDueCount = stats.values.reduce(0) { $0 + $1.dueCount }
        let totalUnlearnedCount = stats.values.reduce(0) { $0 + $1.unlearnedCount }

        NavigationStack(path: $navigationPath) {
            ScrollView {
                VStack(spacing: skin.spacing.sectionGap) {
                    if !pendingEntries.isEmpty {
                        TipView(SyncPendingTip())
                            .padding(.horizontal, skin.metrics.listRowHorizontalInset)
                    }

                    if totalDueCount > 0 || totalUnlearnedCount > 0 {
                        VocabReviewBanner(
                            dueCount: filteredDueEntries.count,
                            unlearnedCount: filteredUnlearnedEntries.count,
                            onStartDue: { startReview(with: filteredDueEntries) },
                            onStartUnlearned: { startReview(with: filteredUnlearnedEntries) },
                            onStartMixed: { startReview(with: filteredDueEntries + filteredUnlearnedEntries) }
                        ) {
                            NotebookFilterChip(filter: $reviewFilter)
                        }
                        .padding(.horizontal, skin.metrics.pageHorizontalInset)
                    }

                    if notebooks.isEmpty {
                        emptyState
                    } else {
                        LazyVGrid(columns: [layoutMode.notebookGridItem], spacing: AppShellMetrics.sectionSpacing) {
                            ForEach(notebooks) { notebook in
                                let s = stats[notebook.remoteId] ?? NotebookStats()
                                NavigationLink(value: notebook.remoteId) {
                                    NotebookCard(
                                        data: NotebookCardData(
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
                                        ),
                                        actions: NotebookCardActions(
                                            setActive: { setActiveNotebook(notebook.remoteId) },
                                            rename: { editingNotebook = notebook },
                                            editCover: { editingNotebook = notebook },
                                            export: { format in exportNotebook(notebook, format: format) },
                                            delete: { notebookToDelete = notebook },
                                            canDelete: !notebook.isDefault
                                        )
                                    )
                                }
                                .buttonStyle(.plain)
                                .transition(.listSwap)
                            }

                            if authManager.isLoggedIn {
                                Button { showCreateSheet = true } label: {
                                    NotebookAddCard()
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.horizontal, skin.metrics.pageHorizontalInset)
                    }
                }
                .padding(.top, skin.metrics.pageTopInset)
                .padding(.bottom, skin.metrics.pageBottomInset)
            }
            .background(skin.palette.pageBackground)
            .navigationTitle("單字本".localized)
            .largeNavigationBarTitle()
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button {
                        showArchiveList = true
                    } label: {
                        Image(systemName: "archivebox")
                    }
                }

                ToolbarItem(placement: .confirmationAction) {
                    Button {
                        showCreateSheet = true
                    } label: {
                        Image(systemName: "plus")
                    }
                    .disabled(!authManager.isLoggedIn)
                    .keyboardShortcut("n", modifiers: .command)
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
    }

    // MARK: - Export

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

    // MARK: - Empty State

    @ViewBuilder
    private var emptyState: some View {
        if authManager.isLoggedIn {
            VocabSceneShell(phase: .empty(
                title: "還沒有單字本".localized,
                systemImage: "books.vertical",
                description: "同步完成後會自動建立預設單字本".localized
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
        guard !entries.isEmpty else { return }
        activeReviewSession = TodayReviewSession(entries: entries)
    }

    // MARK: - Stats (single-pass O(n))

    struct NotebookStats {
        var cardCount: Int = 0
        var dueCount: Int = 0
        var unlearnedCount: Int = 0
        var reviewedCount: Int = 0
        var pendingCount: Int = 0
        var lastActivity: Date?
    }

    static func computeNotebookStats(_ entries: [VocabularyEntry], pendingEntries: [VocabularyEntry]) -> [String: NotebookStats] {
        let now = Date()
        var result: [String: NotebookStats] = [:]
        for entry in entries {
            result[entry.notebookId, default: NotebookStats()].cardCount += 1
            if entry.reviewCount > 0 && entry.nextReviewAt <= now {
                result[entry.notebookId, default: NotebookStats()].dueCount += 1
            } else if entry.reviewCount == 0 {
                result[entry.notebookId, default: NotebookStats()].unlearnedCount += 1
            } else {
                result[entry.notebookId, default: NotebookStats()].reviewedCount += 1
            }
            let activity = entry.lastReviewedAt ?? entry.dateAdded
            if result[entry.notebookId]?.lastActivity == nil || activity > result[entry.notebookId]!.lastActivity! {
                result[entry.notebookId, default: NotebookStats()].lastActivity = activity
            }
        }
        for entry in pendingEntries {
            result[entry.notebookId, default: NotebookStats()].pendingCount += 1
        }
        return result
    }

    static func computeFilteredEntries(_ entries: [VocabularyEntry], filter: NotebookFilter) -> ([VocabularyEntry], [VocabularyEntry]) {
        let now = Date()
        var due: [VocabularyEntry] = []
        var unlearned: [VocabularyEntry] = []
        for entry in entries where filter.matches(entry.notebookId) {
            if entry.reviewCount > 0 && entry.nextReviewAt <= now {
                due.append(entry)
            } else if entry.reviewCount == 0 {
                unlearned.append(entry)
            }
        }
        return (due, unlearned)
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

    @AppStorage("kg_detail_panel_width") private var panelWidth: Double = Double(AppMetrics.MacDetailPanel.defaultWidth)
    @State private var dragWidth: CGFloat?
    @State private var containerWidth: CGFloat = 800

    private var effectivePanelWidth: CGFloat {
        let desired = CGFloat(panelWidth)
        let maxAllowed = containerWidth - AppMetrics.MacDetailPanel.leftMinWidth
        return min(desired, max(maxAllowed, AppMetrics.MacDetailPanel.minWidth))
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
                                            panelWidth = Double(AppMetrics.MacDetailPanel.defaultWidth)
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
                        TodayReviewView(
                            entries: session.entries,
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
            TodayReviewView(
                entries: session.entries,
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
