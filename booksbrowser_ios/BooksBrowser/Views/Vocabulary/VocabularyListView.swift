//
//  VocabularyListView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import UniformTypeIdentifiers

/// 生詞庫列表
struct VocabularyListView: View {
    @Query(sort: \VocabularyEntry.dateAdded, order: .reverse) private var allEntries: [VocabularyEntry]
    @Environment(\.modelContext) private var modelContext

    @State private var searchText = ""
    @State private var showExportSheet = false
    @State private var showSyncView = false
    @State private var showSettings = false
    @State private var exportURL: URL?
    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @State private var selectedTab = 0  // 0 = 我的生詞, 1 = KG 字庫
    @State private var isForceRefreshing = false
    @State private var selectedEntry: VocabularyEntry?

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Segmented toggle
                Picker("", selection: $selectedTab) {
                    Text("待收錄").tag(0)
                    Text("知識庫 (\(authManager.isLoggedIn ? kgService.serverCardCount : 0))").tag(1)
                    Text("關聯圖").tag(2)
                }
                .pickerStyle(.segmented)
                .padding(.horizontal)
                .padding(.vertical, 8)

                // Content
                Group {
                    if selectedTab == 0 {
                        localVocabContent
                    } else if !authManager.isLoggedIn {
                        loggedOutState
                    } else if selectedTab == 1 {
                        KGVocabView(searchText: $searchText)
                    } else {
                        KnowledgeGraphView()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .animation(.none, value: selectedTab)
            }
            .navigationTitle("生詞庫")
            .navigationBarTitleDisplayMode(.large)
            .toolbarBackground(.hidden, for: .navigationBar)
            .toolbar {
                // Sync button
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        showSyncView = true
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "arrow.triangle.2.circlepath")
                                .font(.system(size: 16, weight: .thin))
                            if pendingCount > 0 {
                                Text("\(pendingCount)")
                                    .font(.system(size: 10, weight: .semibold))
                                    .padding(.horizontal, 5)
                                    .padding(.vertical, 1)
                                    .background(AppColors.destructiveLight.opacity(0.85))
                                    .foregroundStyle(.white)
                                    .clipShape(Capsule())
                            }
                        }
                    }
                }

                // Force refresh (知識庫 tab only)
                if selectedTab == 1 && authManager.isLoggedIn {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button {
                            Task { await forceRefresh() }
                        } label: {
                            if isForceRefreshing {
                                ProgressView().scaleEffect(0.8)
                            } else {
                                Image(systemName: "arrow.clockwise")
                                    .font(.system(size: 16, weight: .thin))
                            }
                        }
                        .disabled(isForceRefreshing)
                    }
                }

                // Export menu (only for local vocab tab)
                if selectedTab == 0 && !pendingEntries.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button {
                                exportCSV()
                            } label: {
                                Label("匯出 CSV", systemImage: "tablecells")
                            }

                            Button {
                                exportJSON()
                            } label: {
                                Label("匯出 JSON", systemImage: "doc.text")
                            }

                            Button {
                                exportAnki()
                            } label: {
                                Label("匯出 Anki TSV", systemImage: "rectangle.stack")
                            }
                        } label: {
                            Image(systemName: "square.and.arrow.up")
                                .font(.system(size: 16, weight: .thin))
                        }
                    }
                }
            }
            .sheet(isPresented: $showSyncView) {
                SyncView()
            }
            .sheet(isPresented: $showSettings) {
                SettingsView()
            }
            .sheet(item: $exportURL) { url in
                ShareSheet(url: url)
            }
            .sheet(item: $selectedEntry) { entry in
                WordDetailSheet(entry: entry)
                    .presentationDetents([.medium, .large])
                    .presentationDragIndicator(.visible)
                    .presentationContentInteraction(.scrolls)
            }
            .task {
                await kgService.healthCheck()
            }
            .searchable(text: $searchText, prompt: selectedTab == 0 ? "搜尋單字..." : "搜尋知識庫...")
            .onChange(of: selectedTab) { _, _ in
                searchText = ""  // 清空搜尋
            }
        }
        .vocabSkin(.mochiNeutral)
    }

    // MARK: - Local Vocab Content

    @ViewBuilder
    private var localVocabContent: some View {
        if filteredEntries.isEmpty {
            ContentUnavailableView(
                "沒有待收錄的生詞",
                systemImage: "character.book.closed",
                description: Text("閱讀時點擊的單字會出現在這裡，同步後移入知識庫")
            )
        } else {
            List {
                ForEach(filteredEntries) { entry in
                    WordRow(
                        word: entry.word,
                        translation: entry.translation,
                        partOfSpeech: nil,
                        difficultyTier: entry.difficultyTier,
                        bookTitle: entry.bookTitle,
                        chapterTitle: entry.chapterTitle,
                        nextReviewAt: entry.nextReviewAt,
                        reviewState: nil,
                        syncStatus: nil,
                        actionType: entry.actionType
                    )
                    .contentShape(Rectangle())
                    .onTapGesture { selectedEntry = entry }
                }
                .onDelete(perform: deleteEntries)
            }
            .listStyle(.insetGrouped)
        }
    }

    // MARK: - Computed

    /// Entries not yet synced to KG (待收錄)
    private var pendingEntries: [VocabularyEntry] {
        allEntries.filter { $0.syncStatus != 1 }
    }

    private var pendingCount: Int {
        pendingEntries.count
    }

    private var filteredEntries: [VocabularyEntry] {
        let sortedPending = pendingEntries.sorted {
            if $0.isReviewDue != $1.isReviewDue {
                return $0.isReviewDue && !$1.isReviewDue
            }
            if $0.nextReviewAt != $1.nextReviewAt {
                return $0.nextReviewAt < $1.nextReviewAt
            }
            return $0.dateAdded > $1.dateAdded
        }

        if searchText.isEmpty { return sortedPending }
        return sortedPending.filter {
            $0.word.localizedCaseInsensitiveContains(searchText) ||
            $0.translation.localizedCaseInsensitiveContains(searchText)
        }
    }

    // MARK: - 強制刷新

    private func forceRefresh() async {
        guard !isForceRefreshing else { return }
        isForceRefreshing = true
        await kgService.clearLocalData(container: modelContext.container, reason: "force_refresh")
        try? await kgService.pullCardsToLocal(container: modelContext.container, progress: nil)
        await kgService.healthCheck()
        isForceRefreshing = false
    }

    // MARK: - 刪除

    private func deleteEntries(at offsets: IndexSet) {
        for index in offsets {
            let entry = filteredEntries[index]
            if entry.actionType == "delete" {
                entry.syncStatus = 1
                entry.actionType = "add"
            } else {
                modelContext.delete(entry)
            }
        }
        try? modelContext.save()
    }

    // MARK: - 匯出功能（委派給 VocabularyExporter）

    private func exportCSV()  { exportURL = VocabularyExporter.exportAsCSV(entries: pendingEntries) }
    private func exportJSON() { exportURL = VocabularyExporter.exportAsJSON(entries: pendingEntries) }
    private func exportAnki() { exportURL = VocabularyExporter.exportAsAnki(entries: pendingEntries) }

    @ViewBuilder
    private var loggedOutState: some View {
        ContentUnavailableView {
            Label("需登入帳號", systemImage: "person.crop.circle.badge.exclamationmark")
        } description: {
            Text("知識庫與關聯圖功能需要登入帳號後才能存取您的雲端資料。")
        } actions: {
            Button("前往設定登入") {
                showSettings = true
            }
            .buttonStyle(.borderedProminent)
            .buttonBorderShape(.capsule)
        }
    }
}

// MARK: - 分享表

struct ShareSheet: UIViewControllerRepresentable {
    let url: URL

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: [url], applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

// MARK: - URL Identifiable

extension URL: @retroactive Identifiable {
    public var id: String { absoluteString }
}
