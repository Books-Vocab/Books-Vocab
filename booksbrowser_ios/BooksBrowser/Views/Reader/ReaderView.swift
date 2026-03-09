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

/// 閱讀器主介面（Readium 版）
struct ReaderView: View {
    @Bindable var book: Book
    @Environment(\.modelContext) private var modelContext
    @Environment(\.dismiss) private var dismiss
    @Environment(\.readiumService) private var readiumService
    @Query(
        filter: #Predicate<VocabularyEntry> { $0.actionType != VocabularySyncAction.delete.rawValue }
    )
    private var allVocabulary: [VocabularyEntry]  // 全域生詞（跨書）

    @State private var publication: Publication?
    @State private var isLoading = true
    @State private var isWebViewReady = false
    @State private var loadingPhase = L10n.string("開啟書本…")
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

    // 閱讀殼層狀態：集中 header / overlay / blocker 的控制面
    @State private var chromeState = ReaderChromeState()

    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) private var authManager
    @Environment(\.subscriptionManager) private var subscriptionManager

    // 目錄
    @State private var showTableOfContents = false

    // 閱讀設定（全域單例）
    private var settings = ReaderSettings.shared
    @State private var showSubscriptionPaywall = false

    private var viewConfiguration: ReaderViewConfiguration {
        settings.viewConfiguration
    }

    private var appTheme: AppTheme {
        AppTheme.resolve(for: viewConfiguration.swiftUIColorScheme)
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
        } settingsPanel: {
            settingsPanelContent
        }
        .vocabSkin(VocabSkin.themed(appTheme))
        .preferredColorScheme(viewConfiguration.swiftUIColorScheme)
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
        .sheet(isPresented: glassReaderSettingsBinding) {
            ReaderSettingsPanel(
                settings: settings,
                onDismiss: {
                    closeOverlay(.settings)
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
            .presentationBackground(.ultraThinMaterial)
            .preferredColorScheme(viewConfiguration.swiftUIColorScheme)
        }
        .sheet(isPresented: $showSubscriptionPaywall) {
            SubscriptionPaywallSheet()
        }
    }

    private var presenterState: ReaderViewPresenterState {
        .init(
            paperColor: viewConfiguration.paperColor,
            isWebViewReady: isWebViewReady,
            loadingPhase: loadingPhase,
            underlineProgress: underlineProgress,
            chrome: chromeState,
            totalProgression: totalProgression,
            bookTitle: book.title,
            panelMode: viewConfiguration.translationPanelMode
        )
    }

    private var glassReaderSettingsBinding: Binding<Bool> {
        Binding(
            get: {
                chromeState.overlay == .settings && viewConfiguration.translationPanelMode == .glass
            },
            set: { isPresented in
                if isPresented {
                    chromeState.overlay = .settings
                    chromeState.header = .compact
                } else if chromeState.overlay == .settings {
                    chromeState.overlay = .none
                }
            }
        )
    }

    private var vocabularyContext: ReaderVocabularyContext {
        ReaderVocabularyContext(
            vocabulary: allVocabulary,
            modelContext: modelContext,
            book: book,
            currentLocator: currentLocator
        )
    }

    @ViewBuilder
    private var readerMainContent: some View {
        if let publication = publication {
            ReadiumNavigatorView(
                publication: publication,
                initialLocator: initialLocator,
                httpServer: readiumService.httpServer,
                lookedUpWords: handler.lookedUpWords,
                bookUniqueWords: handler.bookUniqueWords,
                viewConfiguration: viewConfiguration,
                clearHighlightTrigger: handler.clearHighlightTrigger,
                removeWordTrigger: handler.removeWordTrigger,
                navigateToLocator: navigateToLocator,
                isInteractionBlocked: chromeState.blocksReaderInteraction,
                onLocationChanged: handleLocationChange,
                onWordSelected: handleWordSelected,
                onPhraseSelected: handlePhraseSelected,
                onExplainSelected: { text, context in
                    guard canUseProReaderFeature() else { return }
                    chromeState.overlay = .translation
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
    private var settingsPanelContent: some View {
        if viewConfiguration.translationPanelMode == .vocab {
            ReaderSettingsPanel(
                settings: settings,
                onDismiss: {
                    closeOverlay(.settings)
                }
            )
            .vocabSkin(VocabSkin.themed(appTheme))
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
                isLoggedIn: authManager.isLoggedIn && subscriptionManager.hasProAccess,
                isExpanded: handler.isExpanded,
                explanation: handler.explanationText,
                isLoadingExplanation: handler.isLoadingExplanation,
                statusMessage: handler.statusMessage,
                isExplanationOnly: handler.isExplanationOnly,
                onExpand: { handler.handleExpand() },
                onDelete: {
                    handler.deleteFromVocabulary(selection.word, context: vocabularyContext)
                    closeOverlay(.translation)
                },
                onDismiss: {
                    handler.dismiss()
                    closeOverlay(.translation)
                }
            )
            .environment(\.readerPanelMode, viewConfiguration.translationPanelMode)
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
            await MainActor.run { loadingPhase = L10n.string("開啟書本…") }
            let pub = try await readiumService.openPublication(at: book.epubFileURL)

            await MainActor.run {
                loadingPhase = L10n.string("渲染頁面…")
                publication = pub
                isLoading = false
                handler.loadLookedUpWords(from: allVocabulary)
            }

            // 背景提取這本書的專屬單字庫
            Task {
                let uniqueWords = await readiumService.extractUniqueWords(from: pub)
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
        guard canUseProReaderFeature() else { return }
        chromeState.overlay = .translation
        handler.handleWordSelected(
            word: word,
            context: context,
            vocabularyContext: vocabularyContext
        )
    }

    private func handlePhraseSelected(_ phrase: String, _ context: String) {
        guard canUseProReaderFeature() else { return }
        chromeState.overlay = .translation
        handler.handlePhraseSelected(
            phrase: phrase,
            context: context,
            vocabularyContext: vocabularyContext
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
            chromeState.overlay = .settings
            chromeState.header = .compact
        }
    }

    private func expandHeader() {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
            chromeState.header = .expanded
        }
    }

    private func collapseHeader() {
        withAnimation(.spring(response: 0.4, dampingFraction: 0.8)) {
            chromeState.header = .compact
        }
    }

    private func closeOverlay(_ overlay: ReaderChromeOverlay) {
        guard chromeState.overlay == overlay else { return }
        chromeState.overlay = .none
    }

    // MARK: - 取消選取（再次點擊 highlight 的字或點擊空白處）

    private func handleWordDeselected() {
        if chromeState.overlay == .translation {
            handler.dismiss()
            closeOverlay(.translation)
        } else if chromeState.overlay == .settings {
            withAnimation(.spring(response: 0.3)) {
                closeOverlay(.settings)
            }
            handler.clearHighlightTrigger = UUID()
        } else {
            // 如果沒有開啟任何面板，也要確保清除原生的多字 Highlight 與 active-word
            handler.clearHighlightTrigger = UUID()
        }
    }

    private func canUseProReaderFeature() -> Bool {
        guard authManager.isLoggedIn else { return true }
        guard subscriptionManager.hasProAccess else {
            subscriptionManager.activePaywallSource = .reader
            showSubscriptionPaywall = true
            return false
        }
        return true
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
                            .font(AppFonts.body())
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
