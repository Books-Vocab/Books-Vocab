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

    var body: some View {
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
                        reviewBanner
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
                            .buttonStyle(.pressable)
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
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showArchiveList = true
                    } label: {
                        Image(systemName: "archivebox")
                    }
                }

                ToolbarItem(placement: .topBarTrailing) {
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
            .sheet(isPresented: $showCreateSheet) {
                NotebookEditSheet(mode: .create) { name, color in
                    Task { @MainActor in await createNotebook(name: name, color: color) }
                }
            }
            .sheet(item: $editingNotebook) { notebook in
                NotebookEditSheet(mode: .edit(name: notebook.name, color: notebook.color)) { name, color in
                    Task { @MainActor in await updateNotebook(notebook, name: name, color: color) }
                }
            }
            .fullScreenCover(item: $activeReviewSession) { session in
                TodayReviewView(
                    entries: session.entries,
                    allEntries: allEntries,
                    onClose: { activeReviewSession = nil }
                )
            }
            .sheet(isPresented: $showArchiveList) {
                ArchivedVocabSheet()
            }
            .task {
                await ensureDefaultNotebook()
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
                        deleteNotebook(notebook)
                        notebookToDelete = nil
                    }
                }
            } message: {
                Text("單字本內的單字不會被刪除，將移至預設單字本。".localized)
            }
        }
    }

    // MARK: - Review Banner

    @ViewBuilder
    private var reviewBanner: some View {
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
                    startFilteredReview()
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
        VocabSceneShell(phase: .empty(
            title: "還沒有單字本".localized,
            systemImage: "books.vertical",
            description: "登入後自動建立預設單字本".localized
        )) {
            EmptyView()
        }
    }

    // MARK: - Review Helpers

    private var totalDueCount: Int {
        dueCounts.values.reduce(0, +)
    }

    private var filteredDueEntries: [VocabularyEntry] {
        let now = Date()
        return allEntries.filter {
            $0.nextReviewAt <= now &&
            reviewFilter.matches($0.notebookId)
        }
    }

    private var filteredDueCount: Int { filteredDueEntries.count }

    private func startFilteredReview() {
        let entries = filteredDueEntries
        guard !entries.isEmpty else { return }
        activeReviewSession = TodayReviewSession(entries: entries)
    }

    // MARK: - Card Count Helpers (pre-computed dictionaries, O(n) single pass)

    private var cardCounts: [String: Int] {
        allEntries.reduce(into: [:]) { dict, entry in
            dict[entry.notebookId, default: 0] += 1
        }
    }

    private var dueCounts: [String: Int] {
        let now = Date()
        return allEntries.reduce(into: [:]) { dict, entry in
            if entry.nextReviewAt <= now {
                dict[entry.notebookId, default: 0] += 1
            }
        }
    }

    private func setActiveNotebook(_ id: String) {
        activeNotebookId = id
        UserDefaults.standard.set(id, forKey: "activeNotebookId")
    }

    // MARK: - Notebook Operations

    private func ensureDefaultNotebook() async {
        guard authManager.isLoggedIn else { return }
        guard notebooks.isEmpty else { return }

        do {
            let remoteNotebooks = try await kgService.fetchNotebooks()
            for remote in remoteNotebooks where !remote.isDeleted {
                let nb = Notebook(
                    remoteId: remote.id,
                    name: remote.name,
                    color: remote.color,
                    isDefault: remote.isDefault
                )
                nb.sortOrder = remote.sortOrder
                nb.syncStatus = 1
                modelContext.insert(nb)
            }
            modelContext.safeSave()
        } catch {
            // Fallback: create a local default
            if notebooks.isEmpty {
                let nb = Notebook(remoteId: "default", name: "我的單字本", isDefault: true)
                nb.syncStatus = 1
                modelContext.insert(nb)
                modelContext.safeSave()
            }
        }
    }

    private func createNotebook(name: String, color: String?) async {
        do {
            let remote = try await kgService.createNotebook(name: name, color: color)
            let nb = Notebook(remoteId: remote.id, name: remote.name, color: remote.color)
            nb.syncStatus = 1
            modelContext.insert(nb)
            modelContext.safeSave()
        } catch {
            AppLog.kg.error("createNotebook failed: \(error.localizedDescription)")
        }
    }

    private func updateNotebook(_ notebook: Notebook, name: String, color: String?) async {
        do {
            let remote = try await kgService.updateNotebook(id: notebook.remoteId, name: name, color: color)
            notebook.name = remote.name
            notebook.color = remote.color
            notebook.updatedAt = Date()
            modelContext.safeSave()
        } catch {
            AppLog.kg.error("updateNotebook failed: \(error.localizedDescription)")
        }
    }

    private func deleteNotebook(_ notebook: Notebook) {
        Task { @MainActor in
            do {
                try await kgService.deleteNotebook(id: notebook.remoteId)
                if activeNotebookId == notebook.remoteId {
                    setActiveNotebook("default")
                }
                notebook.isDeleted = true
                notebook.updatedAt = Date()
                modelContext.safeSave()
            } catch {
                toastCoordinator.error("刪除失敗")
                AppLog.kg.error("deleteNotebook failed: \(error.localizedDescription)")
            }
        }
    }
}
