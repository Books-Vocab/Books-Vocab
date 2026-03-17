//
//  NotebookListView.swift
//  BooksBrowser
//
//  單字本列表 — 生詞庫 tab 的入口頁

import SwiftUI
import SwiftData

struct NotebookListView: View {
    @Query(sort: \Notebook.sortOrder) private var notebooks: [Notebook]
    @Query(sort: \VocabularyEntry.dateAdded, order: .reverse) private var allEntries: [VocabularyEntry]
    @Environment(\.modelContext) private var modelContext
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.vocabSkin) private var skin
    @Environment(\.horizontalSizeClass) private var sizeClass

    @State private var showCreateSheet = false
    @State private var editingNotebook: Notebook?
    @State private var activeNotebookId: String = UserDefaults.standard.string(forKey: "activeNotebookId") ?? "default"
    @State private var reviewFilter = NotebookFilter.load()
    @State private var activeReviewSession: TodayReviewSession?

    var body: some View {
        NavigationStack {
            ScrollView {
                LazyVStack(spacing: 0) {
                    // Cross-notebook review section
                    if totalDueCount > 0 {
                        reviewBanner
                            .padding(.bottom, skin.spacing.sectionGap)
                    }

                    if notebooks.isEmpty {
                        emptyState
                    } else {
                        ForEach(notebooks.filter { !$0.isDeleted }) { notebook in
                            NavigationLink(value: notebook.remoteId) {
                                NotebookRow(
                                    name: notebook.name,
                                    cardCount: cardCount(for: notebook.remoteId),
                                    dueCount: dueCount(for: notebook.remoteId),
                                    isActive: notebook.remoteId == activeNotebookId,
                                    color: notebook.color.flatMap { Color(hex: $0) }
                                )
                            }
                            .buttonStyle(.plain)
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
                                        deleteNotebook(notebook)
                                    } label: {
                                        Label("刪除".localized, systemImage: "trash")
                                    }
                                }
                            }

                            if notebook.id != notebooks.filter({ !$0.isDeleted }).last?.id {
                                Divider()
                                    .padding(.leading, skin.metrics.listRowHorizontalInset)
                            }
                        }
                    }
                }
                .padding(.horizontal, skin.metrics.pageHorizontalInset)
            }
            .background(skin.palette.pageBackground)
            .navigationTitle("生詞庫".localized)
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
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
                    Task { await createNotebook(name: name, color: color) }
                }
            }
            .sheet(item: $editingNotebook) { notebook in
                NotebookEditSheet(mode: .edit(name: notebook.name, color: notebook.color)) { name, color in
                    Task { await updateNotebook(notebook, name: name, color: color) }
                }
            }
            .fullScreenCover(item: $activeReviewSession) { session in
                TodayReviewView(
                    entries: session.entries,
                    allEntries: allEntries,
                    onClose: { activeReviewSession = nil }
                )
            }
            .task {
                await ensureDefaultNotebook()
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
        VocabEmptyStateCard(
            title: "還沒有單字本".localized,
            systemImage: "books.vertical",
            description: "登入後自動建立預設單字本".localized
        )
        .padding(.top, skin.spacing.sectionGap)
    }

    // MARK: - Review Helpers

    private var totalDueCount: Int {
        let now = Date()
        return allEntries.filter { $0.shouldAppearInKnowledgeList && $0.nextReviewAt <= now }.count
    }

    private var filteredDueEntries: [VocabularyEntry] {
        let now = Date()
        return allEntries.filter {
            $0.shouldAppearInKnowledgeList &&
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

    // MARK: - Card Count Helpers

    private func cardCount(for notebookId: String) -> Int {
        allEntries.filter { $0.notebookId == notebookId && $0.syncAction != .delete && !$0.isArchived }.count
    }

    private func dueCount(for notebookId: String) -> Int {
        let now = Date()
        return allEntries.filter {
            $0.notebookId == notebookId &&
            $0.shouldAppearInKnowledgeList &&
            $0.nextReviewAt <= now
        }.count
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
        Task {
            do {
                try await kgService.deleteNotebook(id: notebook.remoteId)
                notebook.isDeleted = true
                notebook.updatedAt = Date()
                modelContext.safeSave()
            } catch {
                AppLog.kg.error("deleteNotebook failed: \(error.localizedDescription)")
            }
        }
    }
}
