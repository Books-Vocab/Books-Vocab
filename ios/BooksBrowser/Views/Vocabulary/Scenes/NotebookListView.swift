//
//  NotebookListView.swift
//  BooksBrowser
//
//  單字本列表 — 生詞庫 tab 的入口頁

import SwiftUI
import SwiftData
import TipKit

struct NotebookListView: View {
    @Query(filter: #Predicate<Notebook> { !$0.isDeleted }, sort: \Notebook.sortOrder)
    private var notebooks: [Notebook]
    /// Predicate 對應 shouldAppearInKnowledgeList：synced + 非 delete + 非 archived
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
    @State private var activeNotebookId: String = UserDefaults.standard.string(forKey: "activeNotebookId") ?? "default"
    @State private var reviewFilter = NotebookFilter.load()
    @State private var activeReviewSession: TodayReviewSession?
    @State private var notebookToDelete: Notebook?
    @State private var showArchiveList = false
    @State private var navigationPath = NavigationPath()
    #if os(macOS)
    @State private var macDetail = MacDetailState()
    @State private var isEditingMacDetailEntry = false
    #elseif os(iOS)
    @State private var sheetRouter = SheetDetailRouter()
    #endif

    var body: some View {
        // Single-pass: compute cardCounts & dueCounts together
        let (cardCounts, dueCounts) = Self.computeCounts(allEntries)
        let totalDueCount = dueCounts.values.reduce(0, +)
        let filteredDueEntries = Self.computeFilteredDueEntries(allEntries, filter: reviewFilter)
        let filteredDueCount = filteredDueEntries.count

        NavigationStack(path: $navigationPath) {
            ScrollView {
                LazyVStack(spacing: 0) {
                    if !pendingEntries.isEmpty {
                        TipView(SyncPendingTip())
                            .padding(.horizontal, skin.metrics.listRowHorizontalInset)
                            .padding(.bottom, skin.spacing.sectionGap)
                    }

                    // Cross-notebook review section
                    if totalDueCount > 0 {
                        reviewBannerContent(filteredDueCount: filteredDueCount, filteredDueEntries: filteredDueEntries)
                            .padding(.bottom, skin.spacing.sectionGap)
                    }

                    if notebooks.isEmpty {
                        emptyState
                    } else {
                        ForEach(notebooks) { notebook in
                            NavigationLink(value: notebook.remoteId) {
                                NotebookRow(
                                    name: notebook.name,
                                    cardCount: cardCounts[notebook.remoteId] ?? 0,
                                    dueCount: dueCounts[notebook.remoteId] ?? 0,
                                    isActive: notebook.remoteId == activeNotebookId,
                                    color: notebook.color.flatMap { Color(hex: $0) }
                                )
                            }
                            .platformListButtonStyle()
                            .transition(.asymmetric(insertion: .listInsert, removal: .listRemove))
                            .contextMenu {
                                Button {
                                    setActiveNotebook(notebook.remoteId)
                                } label: {
                                    Label("設為使用中".localized, systemImage: "checkmark.circle")
                                }

                                Button {
                                    editingNotebook = notebook
                                } label: {
                                    Label("編輯".localized, systemImage: "pencil")
                                }

                                if !notebook.isDefault {
                                    Divider()
                                    Button(role: .destructive) {
                                        notebookToDelete = notebook
                                    } label: {
                                        Label("刪除".localized, systemImage: "trash")
                                    }
                                }
                            }

                            if notebook.id != notebooks.last?.id {
                                Divider()
                                    .padding(.leading, skin.metrics.listRowHorizontalInset)
                            }
                        }
                    }
                }
                .padding(.horizontal, skin.metrics.pageHorizontalInset)
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
                }
            }
            .navigationDestination(for: String.self) { notebookId in
                VocabularyListView(notebookId: notebookId)
            }
            .toastSheet(isPresented: $showCreateSheet) {
                NotebookEditSheet(mode: .create) { name, color in
                    Task { @MainActor in
                        await coordinator.createNotebook(name: name, color: color, modelContext: modelContext, kgService: kgService, toastCoordinator: toastCoordinator)
                    }
                }
            }
            .toastSheet(item: $editingNotebook) { notebook in
                NotebookEditSheet(mode: .edit(name: notebook.name, color: notebook.color)) { name, color in
                    Task { @MainActor in
                        await coordinator.updateNotebook(notebook, name: name, color: color, modelContext: modelContext, kgService: kgService, toastCoordinator: toastCoordinator)
                    }
                }
            }
            .onChange(of: activeReviewSession) { _, session in
                if let session {
                    #if os(macOS)
                    macDetail.showReview(session, allEntries: allEntries)
                    #elseif os(iOS)
                    sheetRouter.showReview(session, allEntries: allEntries)
                    #endif
                    activeReviewSession = nil
                }
            }
            .toastSheet(isPresented: $showArchiveList) {
                ArchivedVocabSheet()
            }
            .task(id: authManager.isLoggedIn) {
                await coordinator.ensureDefaultNotebook(
                    authManager: authManager,
                    currentNotebooks: notebooks,
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
                Text("單字本內的單字不會被刪除，將移至預設單字本。".localized)
            }
        }
        #if os(iOS)
        .environment(\.detailRouter, sheetRouter)
        .toastSheet(item: $sheetRouter.selectedEntry) { entry in
            WordDetailSheet(entry: entry, allEntries: sheetRouter.contextEntries)
                .appSheet(.large)
        }
        .platformFullScreenCover(item: Binding(
            get: { sizeClass == .compact ? sheetRouter.activeReviewSession : nil },
            set: { if $0 == nil { sheetRouter.dismiss() } }
        )) { session in
            TodayReviewView(
                entries: session.entries,
                allEntries: sheetRouter.contextEntries.isEmpty ? allEntries : sheetRouter.contextEntries,
                currentUserID: authManager.userId,
                onClose: { sheetRouter.dismiss() }
            )
            .toastOverlay()
        }
        .toastSheet(item: Binding(
            get: { sizeClass == .regular ? sheetRouter.activeReviewSession : nil },
            set: { if $0 == nil { sheetRouter.dismiss() } }
        )) { session in
            TodayReviewView(
                entries: session.entries,
                allEntries: sheetRouter.contextEntries.isEmpty ? allEntries : sheetRouter.contextEntries,
                currentUserID: authManager.userId,
                onClose: { sheetRouter.dismiss() }
            )
            .appSheet(.large)
        }
        #elseif os(macOS)
        .environment(\.detailRouter, macDetail)
        .safeAreaInset(edge: .trailing, spacing: 0) {
            if macDetail.hasDetail {
                HStack(spacing: 0) {
                    Divider()
                    macDetailPanel
                        .frame(minWidth: 350, idealWidth: 420, maxWidth: 600)
                }
                .transition(.move(edge: .trailing).combined(with: .opacity))
            }
        }
        .animation(AppMotion.standardSpring, value: macDetail.hasDetail)
        .onChange(of: navigationPath) { _, path in
            if path.isEmpty { macDetail.dismiss() }
        }
        .onChange(of: macDetail.selectedEntry?.id) { _, entryID in
            if entryID == nil {
                isEditingMacDetailEntry = false
            }
        }
        .toastSheet(isPresented: Binding(
            get: { isEditingMacDetailEntry && macDetail.selectedEntry != nil },
            set: { isEditingMacDetailEntry = $0 }
        )) {
            if let entry = macDetail.selectedEntry {
                WordEditSheet(entry: entry)
            }
        }
        #endif
    }

    // MARK: - Review Banner

    @ViewBuilder
    private func reviewBannerContent(filteredDueCount: Int, filteredDueEntries: [VocabularyEntry]) -> some View {
        VStack(spacing: skin.spacing.inlineGap) {
            HStack {
                VStack(alignment: .leading, spacing: skin.spacing.microGap) {
                    Text("今日複習".localized)
                        .font(skin.typography.captionStrong)
                        .foregroundStyle(skin.palette.primaryText)

                    Text(L10n.format("%@ 張卡片到期", "\(filteredDueCount)"))
                        .font(skin.typography.caption)
                        .foregroundStyle(skin.palette.secondaryText)
                }

                Spacer()

                NotebookFilterChip(filter: $reviewFilter)

                Button {
                    startReview(with: filteredDueEntries)
                } label: {
                    Label("開始".localized, systemImage: "play.fill")
                        .font(skin.typography.captionStrong)
                }
                .buttonStyle(.borderedProminent)
                .controlSize(.small)
                .disabled(filteredDueEntries.isEmpty)
            }
        }
        .padding(skin.spacing.cardPadding)
        .background(skin.palette.cardBackground, in: RoundedRectangle(cornerRadius: skin.radii.card))
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

    #if os(macOS)
    @ViewBuilder
    private var macDetailPanel: some View {
        if let session = macDetail.activeReviewSession {
            TodayReviewView(
                entries: session.entries,
                allEntries: macDetail.contextEntries.isEmpty ? allEntries : macDetail.contextEntries,
                currentUserID: authManager.userId,
                onClose: { macDetail.dismiss() }
            )
        } else if let entry = macDetail.selectedEntry {
            VStack(spacing: 0) {
                VocabOverlayHeader(
                    title: entry.word,
                    systemImage: "character.book.closed",
                    onClose: { macDetail.dismiss() },
                    trailing: {
                        VocabChromeIconButton(
                            systemImage: "pencil",
                            label: "編輯".localized,
                            action: { isEditingMacDetailEntry = true }
                        )
                    }
                )

                WordDetailSheet(
                    entry: entry,
                    allEntries: macDetail.contextEntries,
                    wrapInNavigation: false,
                    showsInlineChrome: false
                )
            }
        }
    }
    #endif

    // MARK: - Card Count Helpers (single-pass O(n))

    /// Returns (cardCounts, dueCounts) in one iteration over allEntries.
    private static func computeCounts(_ entries: [VocabularyEntry]) -> ([String: Int], [String: Int]) {
        let now = Date()
        var card: [String: Int] = [:]
        var due: [String: Int] = [:]
        for entry in entries {
            card[entry.notebookId, default: 0] += 1
            if entry.nextReviewAt <= now {
                due[entry.notebookId, default: 0] += 1
            }
        }
        return (card, due)
    }

    private static func computeFilteredDueEntries(_ entries: [VocabularyEntry], filter: NotebookFilter) -> [VocabularyEntry] {
        let now = Date()
        return entries.filter {
            $0.nextReviewAt <= now &&
            filter.matches($0.notebookId)
        }
    }

    private func setActiveNotebook(_ id: String) {
        activeNotebookId = id
        UserDefaults.standard.set(id, forKey: "activeNotebookId")
    }

}
