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
                                exportAsCSV()
                            } label: {
                                Label("匯出 CSV", systemImage: "tablecells")
                            }

                            Button {
                                exportAsJSON()
                            } label: {
                                Label("匯出 JSON", systemImage: "doc.text")
                            }

                            Button {
                                exportAsAnki()
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
            }
            .task {
                await kgService.healthCheck()
            }
            .searchable(text: $searchText, prompt: selectedTab == 0 ? "搜尋單字..." : "搜尋知識庫...")
            .onChange(of: selectedTab) { _, _ in
                searchText = ""  // 清空搜尋
            }
        }
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

    // MARK: - 匯出功能

    private func exportAsCSV() {
        var csv = "Word,Translation,Part of Speech,Pronunciation,Context,Book,Chapter,Date\n"
        for entry in pendingEntries {
            let fields = [
                escapeCSV(entry.word),
                escapeCSV(entry.translation),
                escapeCSV(""),
                escapeCSV(entry.pronunciation ?? ""),
                escapeCSV(entry.context),
                escapeCSV(entry.bookTitle),
                escapeCSV(entry.chapterTitle ?? ""),
                escapeCSV(entry.dateAdded.formatted(.iso8601))
            ]
            csv += fields.joined(separator: ",") + "\n"
        }
        saveAndShare(content: csv, filename: "vocabulary.csv")
    }

    private func exportAsJSON() {
        let items = pendingEntries.map { entry -> [String: String] in
            var dict: [String: String] = [
                "word": entry.word,
                "translation": entry.translation,
                "context": entry.context,
                "bookTitle": entry.bookTitle,
                "dateAdded": entry.dateAdded.formatted(.iso8601)
            ]

            if let pron = entry.pronunciation { dict["pronunciation"] = pron }
            if let exp = entry.explanation { dict["explanation"] = exp }
            if let ch = entry.chapterTitle { dict["chapterTitle"] = ch }
            return dict
        }

        if let data = try? JSONSerialization.data(withJSONObject: items, options: .prettyPrinted),
           let json = String(data: data, encoding: .utf8) {
            saveAndShare(content: json, filename: "vocabulary.json")
        }
    }

    private func exportAsAnki() {
        var tsv = ""
        for entry in pendingEntries {
            let front = "\(entry.word)\n<small>\(entry.context)</small>"
            var back = entry.translation

            if let pron = entry.pronunciation { back += "\n\(pron)" }
            if let exp = entry.explanation { back += "\n\(exp)" }

            tsv += "\(escapeTab(front))\t\(escapeTab(back))\n"
        }
        saveAndShare(content: tsv, filename: "vocabulary_anki.tsv")
    }

    private func saveAndShare(content: String, filename: String) {
        let tempURL = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
        try? content.write(to: tempURL, atomically: true, encoding: .utf8)
        exportURL = tempURL
    }

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

    private func escapeCSV(_ text: String) -> String {
        let escaped = text.replacingOccurrences(of: "\"", with: "\"\"")
        return "\"\(escaped)\""
    }

    private func escapeTab(_ text: String) -> String {
        text.replacingOccurrences(of: "\t", with: " ")
            .replacingOccurrences(of: "\n", with: "<br>")
    }
}

// MARK: - 統一單字行元件

/// 共用單字列表行 — 待收錄和知識庫都使用相同版面
/// 極簡知識美學：高留白、線性圖標、文字驅動層級
struct WordRow: View {
    @Environment(\.colorScheme) private var colorScheme
    let word: String
    let translation: String
    let partOfSpeech: String?
    let difficultyTier: String?
    let bookTitle: String?
    let chapterTitle: String?
    let nextReviewAt: Date
    let reviewState: VocabularyReviewState?
    let syncStatus: Int?
    var actionType: String = "add"  // "add" | "delete"

    private var isDelete: Bool { actionType == "delete" }
    private var isDue: Bool { nextReviewAt <= Date() }

    var body: some View {
        HStack(alignment: .top, spacing: AppMetrics.spacingMedium) {
            VStack(alignment: .leading, spacing: 6) {
                // Row 1: word + POS
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    if isDelete {
                        Image(systemName: "trash")
                            .font(.system(size: 12, weight: .thin))
                            .foregroundStyle(AppColors.destructive(colorScheme))
                    }

                    Text(word)
                        .font(.system(size: 20, weight: .semibold, design: .serif))
                        .strikethrough(isDelete, color: AppColors.destructive(colorScheme))
                        .foregroundStyle(isDelete ? AppColors.destructive(colorScheme) : .primary)

                    if let pos = partOfSpeech {
                        Text(pos)
                            .font(.system(size: 11, weight: .medium))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(AppColors.accent(colorScheme).opacity(0.10))
                            .foregroundStyle(AppColors.accent(colorScheme))
                            .clipShape(Capsule())
                    }

                    if isDelete {
                        Spacer()
                        Text("待刪除")
                            .font(.system(size: 11, weight: .medium))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(AppColors.destructive(colorScheme).opacity(0.08))
                            .foregroundStyle(AppColors.destructive(colorScheme))
                            .clipShape(Capsule())
                    }
                }

                // Row 2: translation
                if !isDelete {
                    if translation.isEmpty {
                        Label("待翻譯", systemImage: "clock")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    } else {
                        Text(translation)
                            .font(.system(size: 15, weight: .regular))
                            .foregroundStyle(AppColors.translation(colorScheme))
                            .lineSpacing(3)
                    }
                }

                // Row 3: source (待收錄 only)
                if let book = bookTitle, !book.isEmpty {
                    HStack(spacing: 4) {
                        Image(systemName: "book.closed")
                            .font(.system(size: 10, weight: .thin))
                        Text(book)
                            .font(.caption2)
                        if let chapter = chapterTitle {
                            Text("· \(chapter)")
                                .font(.caption2)
                        }
                    }
                    .foregroundStyle(.tertiary)
                }

                // Row 4: review status
                if !isDelete {
                    HStack(spacing: 6) {
                        Image(systemName: statusIconName)
                            .font(.system(size: 10, weight: .thin))
                        Text(statusSubtitle)
                            .font(.caption2)
                    }
                    .foregroundStyle(statusTone)
                }
            }

            Spacer(minLength: 0)

            // Top-right: difficulty tier (borderless, lightweight text)
            if let tier = difficultyTier, !isDelete {
                VStack(alignment: .trailing, spacing: 6) {
                    tierLabel(tier)

                    if let reviewState {
                        reviewStateBadge(reviewState)
                    }
                }
            }
        }
        .padding(.vertical, 8)
    }

    // MARK: - Badges

    private func tierLabel(_ tier: String) -> some View {
        let (color, label) = AppColors.tier(tier, scheme: colorScheme)

        return Text(label)
            .font(.system(size: 10, weight: .medium, design: .monospaced))
            .foregroundStyle(color.opacity(0.65))
    }

    private var statusSubtitle: String {
        switch reviewState {
        case .unlearned:
            return "尚未進入複習流程"
        case .due:
            return "現在可複習"
        case .reviewed:
            return "下次 \(nextReviewAt.reviewRelativeDescription())"
        case nil:
            return isDue ? "現在可複習" : "下次 \(nextReviewAt.reviewRelativeDescription())"
        }
    }

    private var statusIconName: String {
        switch reviewState {
        case .unlearned:
            return "sparkles"
        case .due:
            return "clock.badge.exclamationmark"
        case .reviewed:
            return "checkmark.circle"
        case nil:
            return isDue ? "clock.badge.exclamationmark" : "clock.arrow.trianglehead.counterclockwise.rotate.90"
        }
    }

    private var statusTone: Color {
        switch reviewState {
        case .unlearned:
            return AppColors.accent(colorScheme)
        case .due:
            return AppColors.translation(colorScheme)
        case .reviewed:
            return AppColors.saved(colorScheme)
        case nil:
            return isDue ? AppColors.translation(colorScheme) : Color.secondary.opacity(0.7)
        }
    }

    private func reviewStateBadge(_ state: VocabularyReviewState) -> some View {
        Text(state.title)
            .font(.system(size: 10, weight: .semibold, design: .rounded))
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .background(statusTone.opacity(0.08))
            .foregroundStyle(statusTone)
            .clipShape(Capsule())
    }

    @ViewBuilder
    private func syncIcon(_ status: Int) -> some View {
        switch status {
        case 1:
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 12, weight: .thin))
                .foregroundStyle(AppColors.saved(colorScheme).opacity(0.7))
        case 2:
            Image(systemName: "exclamationmark.circle.fill")
                .font(.system(size: 12, weight: .thin))
                .foregroundStyle(AppColors.destructive(colorScheme).opacity(0.7))
        default:
            Image(systemName: "clock")
                .font(.system(size: 12, weight: .thin))
                .foregroundStyle(.tertiary)
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
