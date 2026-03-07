//
//  ReaderView.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import ReadiumShared
import ReadiumNavigator

/// 浮動導覽列狀態
enum HeaderState {
    case compact
    case expanded
}

/// 閱讀器主介面（Readium 版）
struct ReaderView: View {
    @Bindable var book: Book
    @Environment(\.modelContext) private var modelContext
    @Environment(\.dismiss) private var dismiss
    @Query(
        filter: #Predicate<VocabularyEntry> { $0.actionType != "delete" }
    )
    private var allVocabulary: [VocabularyEntry]  // 全域生詞（跨書）

    @State private var publication: Publication?
    @State private var isLoading = true
    @State private var isWebViewReady = false
    @State private var loadingPhase = "開啟書本…"
    @State private var errorMessage: String?
    @State private var underlineProgress: Double? = nil
    @State private var hasCompletedInitialMarking = false

    // 翻譯 handler（封裝所有翻譯狀態與詞庫邏輯）
    @State private var handler = ReaderTranslationHandler()

    // 觸發導航
    @State private var navigateToLocator: (locator: Locator, id: UUID)? = nil

    // 進度
    @State private var currentLocator: Locator?
    @State private var totalProgression: Double = 0

    // 浮動 header 顯示狀態
    @State private var headerState: HeaderState = .compact

    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager

    // 目錄
    @State private var showTableOfContents = false

    // 閱讀設定（全域單例）
    private var settings = ReaderSettings.shared
    @State private var showReaderSettings = false

    // 紙張背景色，填補 safeAreaInset 造成的系統預設白邊
    private var paperColor: SwiftUI.Color {
        switch settings.theme {
        case .light: return AppColors.paperLight
        case .sepia: return AppColors.paperSepia
        case .dark:  return AppColors.paperDark
        }
    }

    init(book: Book) {
        self._book = Bindable(book)
    }

    var body: some View {
        ReaderViewPresenter(
            state: presenterState,
            onDismiss: { dismiss() },
            onShowTableOfContents: { showTableOfContents = true },
            onShowReaderSettings: showReaderSettingsPanel,
            onExpandHeader: expandHeader,
            onCollapseHeader: collapseHeader
        ) {
            readerMainContent
        } translationPanel: {
            translationPanelContent
        }
        .preferredColorScheme(settings.swiftUIColorScheme)
        .tint(.secondary)
        .toolbar(.hidden, for: .tabBar)
        .toolbar(.hidden, for: .navigationBar)
        .sheet(isPresented: $showTableOfContents) {
            if let publication = publication {
                TOCView(
                    publication: publication,
                    onSelect: { link in
                        showTableOfContents = false
                        print("📖 TOC selected: \(link.title ?? "Untitled")")
                        Task { @MainActor in
                            if let locator = await publication.locate(link) {
                                print("📖 Navigating to valid locator: \(locator.href)")
                                navigateToLocator = (locator: locator, id: UUID())
                            } else {
                                print("❌ TOC navigation failed: could not locate link \(link)")
                            }
                        }
                    }
                )
            }
        }
        .task {
            await loadPublication()
        }
        .onChange(of: allVocabulary) { _, _ in
            handler.loadLookedUpWords(from: allVocabulary)
        }
        .onChange(of: authManager.isLoggedIn) { _, loggedIn in
            // 登出時立刻清空底線，不等 SwiftData async clear 通知
            if !loggedIn {
                handler.lookedUpWords = []
                handler.bookUniqueWords = nil
                handler.clearHighlightTrigger = UUID()
            }
        }
        .sheet(isPresented: $showReaderSettings) {
            ReaderSettingsPanel(
                settings: settings,
                onDismiss: {
                    showReaderSettings = false
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
            .presentationBackground(.ultraThinMaterial)
            .preferredColorScheme(settings.swiftUIColorScheme)
        }
    }

    private var presenterState: ReaderViewPresenterState {
        .init(
            paperColor: paperColor,
            isWebViewReady: isWebViewReady,
            loadingPhase: loadingPhase,
            underlineProgress: underlineProgress,
            showsTranslationPanel: handler.showTranslationPanel,
            showsReaderSettings: showReaderSettings,
            headerState: headerState,
            totalProgression: totalProgression,
            bookTitle: book.title
        )
    }

    @ViewBuilder
    private var readerMainContent: some View {
        if let publication = publication {
            ReadiumNavigatorView(
                publication: publication,
                initialLocator: initialLocator,
                httpServer: ReadiumService.shared.httpServer,
                lookedUpWords: handler.lookedUpWords,
                bookUniqueWords: handler.bookUniqueWords,
                preferences: settings.epubPreferences,
                clearHighlightTrigger: handler.clearHighlightTrigger,
                removeWordTrigger: handler.removeWordTrigger,
                navigateToLocator: navigateToLocator,
                isInteractionBlocked: handler.showTranslationPanel || showReaderSettings,
                onLocationChanged: handleLocationChange,
                onWordSelected: handleWordSelected,
                onPhraseSelected: handlePhraseSelected,
                onExplainSelected: { text, context in
                    handler.handleExplainSelected(text: text, context: context)
                },
                onWordDeselected: handleWordDeselected,
                onMarkingProgress: handleMarkingProgress
            )
            .ignoresSafeArea(edges: [.horizontal, .bottom])
            .safeAreaInset(edge: .top) {
                Color.clear.frame(height: 0)
            }
        } else if let error = errorMessage {
            ContentUnavailableView(
                "無法開啟書籍",
                systemImage: "exclamationmark.triangle",
                description: Text(error)
            )
        }
    }

    @ViewBuilder
    private var translationPanelContent: some View {
        if let selection = handler.wordSelection {
            TranslationPanel(
                word: selection.word,
                result: handler.translationResult,
                pronunciation: handler.pronunciation,
                isLoading: handler.isTranslating,
                isSaved: handler.isSaved,
                isLoggedIn: authManager.isLoggedIn,
                isExpanded: handler.isExpanded,
                explanation: handler.explanationText,
                isLoadingExplanation: handler.isLoadingExplanation,
                statusMessage: handler.statusMessage,
                isExplanationOnly: handler.isExplanationOnly,
                onExpand: { handler.handleExpand() },
                onDelete: {
                    handler.deleteFromVocabulary(
                        selection.word,
                        vocabulary: allVocabulary,
                        modelContext: modelContext
                    )
                },
                onDismiss: { handler.dismiss() }
            )
        }
    }

    // MARK: - 初始位置

    private var initialLocator: Locator? {
        guard let json = book.lastReadLocatorJSON else { return nil }
        return try? Locator(jsonString: json)
    }

    // MARK: - 載入 Publication

    private func loadPublication() async {
        do {
            await MainActor.run { loadingPhase = "開啟書本…" }
            let pub = try await ReadiumService.shared.openPublication(at: book.epubFileURL)

            await MainActor.run {
                loadingPhase = "渲染頁面…"
                publication = pub
                isLoading = false
                handler.loadLookedUpWords(from: allVocabulary)
            }

            // 背景提取這本書的專屬單字庫
            Task {
                let uniqueWords = await ReadiumService.shared.extractUniqueWords(from: pub)
                await MainActor.run {
                    handler.bookUniqueWords = uniqueWords
                }
            }
        } catch {
            await MainActor.run {
                errorMessage = error.localizedDescription
                isLoading = false
                isWebViewReady = true  // 顯示錯誤畫面
            }
        }
    }

    // MARK: - 位置變更

    private func handleLocationChange(_ locator: Locator) {
        if !isWebViewReady {
            withAnimation(.easeOut(duration: 0.3)) { isWebViewReady = true }
        }
        currentLocator = locator
        totalProgression = locator.locations.totalProgression ?? 0
        book.lastReadLocatorJSON = locator.jsonString
        book.dateLastRead = Date()
        book.progression = totalProgression
    }

    private func handleWordSelected(_ word: String, _ context: String) {
        handler.handleWordSelected(
            word: word,
            context: context,
            vocabulary: allVocabulary,
            modelContext: modelContext,
            book: book,
            currentLocator: currentLocator
        )
    }

    private func handlePhraseSelected(_ phrase: String, _ context: String) {
        handler.handlePhraseSelected(
            phrase: phrase,
            context: context,
            vocabulary: allVocabulary,
            modelContext: modelContext,
            book: book,
            currentLocator: currentLocator
        )
    }

    private func handleMarkingProgress(_ progress: Double) {
        guard !hasCompletedInitialMarking else { return }
        withAnimation(.linear(duration: 0.1)) {
            underlineProgress = progress
        }
        if progress >= 1.0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                withAnimation(.easeOut(duration: 0.3)) {
                    underlineProgress = nil
                }
                hasCompletedInitialMarking = true
            }
        }
    }

    private func showReaderSettingsPanel() {
        withAnimation(.spring(response: 0.3)) {
            showReaderSettings = true
            headerState = .compact
        }
    }

    private func expandHeader() {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
            headerState = .expanded
        }
    }

    private func collapseHeader() {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
            headerState = .compact
        }
    }

    // MARK: - 取消選取（再次點擊 highlight 的字或點擊空白處）

    private func handleWordDeselected() {
        if handler.showTranslationPanel {
            handler.dismiss()
        } else if showReaderSettings {
            withAnimation(.spring(response: 0.3)) {
                showReaderSettings = false
            }
            handler.clearHighlightTrigger = UUID()
        } else {
            // 如果沒有開啟任何面板，也要確保清除原生的多字 Highlight 與 active-word
            handler.clearHighlightTrigger = UUID()
        }
    }
}

// MARK: - 目錄視圖

struct TOCView: View {
    let publication: Publication
    let onSelect: (ReadiumShared.Link) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var tocLinks: [ReadiumShared.Link] = []

    var body: some View {
        NavigationStack {
            List {
                ForEach(tocLinks.indices, id: \.self) { index in
                    let link = tocLinks[index]
                    Button {
                        onSelect(link)
                        dismiss()
                    } label: {
                        Text(link.title ?? "Untitled")
                            .font(.body)
                    }
                }
            }
            .navigationTitle("目錄")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成") { dismiss() }
                }
            }
            .task {
                do {
                    let toc = try await publication.tableOfContents().get()
                    tocLinks = toc
                    print("📖 TOC loaded: \(toc.count) items")
                    for (i, link) in toc.enumerated() {
                        print("  📖 [\(i)] \(link.title ?? "nil") → \(link.url())")
                    }
                    if toc.isEmpty {
                        print("⚠️ TOC is empty — this book may not have a table of contents")
                    }
                } catch {
                    print("❌ TOC load failed: \(error)")
                }
            }
        }
    }
}
