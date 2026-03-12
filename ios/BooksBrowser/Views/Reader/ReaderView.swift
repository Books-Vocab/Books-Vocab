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
import os

/// 閱讀器主介面（Readium 版）
struct ReaderView: View {
    @Bindable var book: Book
    @Environment(\.modelContext) private var modelContext
    @Environment(\.dismiss) private var dismiss
    @Environment(\.readiumService) private var readiumService
    @Query(
        filter: #Predicate<VocabularyEntry> { $0.actionType != "delete" }
    )
    private var allVocabulary: [VocabularyEntry]  // 全域生詞（跨書）

    @State private var publication: Publication?
    @State private var readerState = ReaderViewState()

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
    @Environment(\.readerSettings) private var settings

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
            onShowTableOfContents: { readerState.showTableOfContents = true },
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
        .sheet(isPresented: Binding(get: { readerState.showTableOfContents }, set: { readerState.showTableOfContents = $0 })) {
            if let publication = publication {
                TOCView(
                    publication: publication,
                    onSelect: { link in
                        readerState.showTableOfContents = false
                        AppLog.reader.debug("TOC selected: \(link.title ?? "Untitled")")
                        Task { @MainActor in
                            if let locator = await publication.locate(link) {
                                AppLog.reader.debug("Navigating to valid locator: \(String(describing: locator.href))")
                                navigateToLocator = (locator: locator, id: UUID())
                            } else {
                                AppLog.reader.error("TOC navigation failed: could not locate link \(String(describing: link))")
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
        .sheet(isPresented: Binding(get: { readerState.showSubscriptionPaywall }, set: { readerState.showSubscriptionPaywall = $0 })) {
            SubscriptionPaywallSheet()
        }
    }

    private var presenterState: ReaderViewPresenterState {
        .init(
            paperColor: viewConfiguration.paperColor,
            isWebViewReady: readerState.isWebViewReady,
            loadingPhase: readerState.loadingPhase,
            underlineProgress: readerState.underlineProgress,
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
                    handler.handleExplainSelected(text: text, context: context)
                    withAnimation(AppMotion.panelState) { chromeState.overlay = .translation }
                },
                onWordDeselected: handleWordDeselected,
                onMarkingProgress: handleMarkingProgress
            )
            .ignoresSafeArea(edges: [.horizontal, .bottom])
            .safeAreaInset(edge: .top) {
                Color.clear.frame(height: 0)
            }
        } else if let error = readerState.errorMessage {
            ContentUnavailableView(
                "無法開啟書籍".localized,
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
                isLoggedIn: authManager.isLoggedIn,
                isExpanded: handler.isExpanded,
                explanation: handler.explanationText,
                isLoadingExplanation: handler.isLoadingExplanation,
                statusMessage: handler.statusMessage,
                isExplanationOnly: handler.isExplanationOnly,
                translationErrorMessage: handler.translationErrorMessage,
                explanationErrorMessage: handler.explanationErrorMessage,
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
            let url = book.epubFileURL

            // 確保 iCloud 檔案已下載到本機
            if !FileManager.default.isReadableFile(atPath: url.path) {
                try await ensureICloudFileDownloaded(at: url)
            }

            await MainActor.run { readerState.loadingPhase = L10n.string("開啟書本…") }
            let pub = try await readiumService.openPublication(at: url)

            await MainActor.run {
                readerState.loadingPhase = L10n.string("渲染頁面…")
                publication = pub
                readerState.isLoading = false
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
                readerState.errorMessage = error.localizedDescription
                readerState.isLoading = false
                readerState.isWebViewReady = true  // 顯示錯誤畫面
            }
        }
    }

    // MARK: - iCloud 檔案下載

    /// 觸發 iCloud 下載並等待完成（最多 60 秒）
    private func ensureICloudFileDownloaded(at url: URL) async throws {
        let fm = FileManager.default

        // 嘗試觸發 iCloud 下載；若非 ubiquitous item 會拋錯 → 檔案遺失
        do {
            try fm.startDownloadingUbiquitousItem(at: url)
        } catch {
            AppLog.readium.error("startDownloadingUbiquitousItem failed: \(error.localizedDescription)")
            throw NSError(
                domain: "Book",
                code: 2,
                userInfo: [NSLocalizedDescriptionKey: L10n.string("找不到書籍檔案，請重新匯入。")]
            )
        }

        await MainActor.run {
            readerState.loadingPhase = L10n.string("正在從 iCloud 下載…")
        }
        AppLog.readium.info("iCloud download triggered for: \(url.lastPathComponent)")

        // 輪詢等待檔案就緒
        let deadline = Date().addingTimeInterval(60)
        while Date() < deadline {
            if fm.isReadableFile(atPath: url.path) {
                AppLog.readium.info("iCloud file ready: \(url.lastPathComponent)")
                return
            }
            try await Task.sleep(nanoseconds: 500_000_000)
        }

        AppLog.readium.error("iCloud download timed out: \(url.lastPathComponent)")
        throw NSError(
            domain: "Book",
            code: 3,
            userInfo: [NSLocalizedDescriptionKey: L10n.string("iCloud 下載逾時，請確認網路連線後重試。")]
        )
    }

    // MARK: - 位置變更

    private func handleLocationChange(_ locator: Locator) {
        if !readerState.isWebViewReady {
            withAnimation(AppMotion.loadingState) { readerState.isWebViewReady = true }
        }
        currentLocator = locator
        totalProgression = locator.locations.totalProgression ?? 0
        book.lastReadLocatorJSON = locator.jsonString
        book.dateLastRead = Date()
        book.progression = totalProgression
    }

    private func handleWordSelected(_ word: String, _ context: String) {
        guard canUseProReaderFeature() else { return }
        // handler 先同步設定 wordSelection，確保 translationPanelContent 有內容
        handler.handleWordSelected(
            word: word,
            context: context,
            vocabularyContext: vocabularyContext
        )
        // overlay 動畫事務觸發時 panel 已就緒，.transition() 才會生效
        withAnimation(AppMotion.panelState) { chromeState.overlay = .translation }
    }

    private func handlePhraseSelected(_ phrase: String, _ context: String) {
        guard canUseProReaderFeature() else { return }
        handler.handlePhraseSelected(
            phrase: phrase,
            context: context,
            vocabularyContext: vocabularyContext
        )
        withAnimation(AppMotion.panelState) { chromeState.overlay = .translation }
    }

    private func handleMarkingProgress(_ progress: Double) {
        guard !readerState.hasCompletedInitialMarking else { return }
        withAnimation(AppMotion.progressLinear) {
            readerState.underlineProgress = progress
        }
        if progress >= 1.0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                withAnimation(AppMotion.contentFade) {
                    readerState.underlineProgress = nil
                }
                readerState.hasCompletedInitialMarking = true
            }
        }
    }

    private func showReaderSettingsPanel() {
        withAnimation(AppMotion.panelState) {
            chromeState.overlay = .settings
            chromeState.header = .compact
        }
    }

    private func expandHeader() {
        withAnimation(AppMotion.headerState) {
            chromeState.header = .expanded
        }
    }

    private func collapseHeader() {
        withAnimation(AppMotion.headerState) {
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
            withAnimation(AppMotion.panelState) {
                handler.dismiss()
                closeOverlay(.translation)
            }
        } else if chromeState.overlay == .settings {
            withAnimation(AppMotion.panelState) {
                closeOverlay(.settings)
            }
            handler.clearHighlightTrigger = UUID()
        } else {
            // 如果沒有開啟任何面板，也要確保清除原生的多字 Highlight 與 active-word
            handler.clearHighlightTrigger = UUID()
        }
    }

    private func canUseProReaderFeature() -> Bool {
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
            .navigationTitle("目錄".localized)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("完成".localized) { dismiss() }
                }
            }
            .task {
                do {
                    let toc = try await publication.tableOfContents().get()
                    tocLinks = toc
                    AppLog.reader.info("TOC loaded: \(toc.count) items")
                    for (i, link) in toc.enumerated() {
                        AppLog.reader.debug("  [\(i)] \(link.title ?? "nil") → \(String(describing: link.url()))")
                    }
                    if toc.isEmpty {
                        AppLog.reader.warning("TOC is empty — this book may not have a table of contents")
                    }
                } catch {
                    AppLog.reader.error("TOC load failed: \(error.localizedDescription)")
                }
            }
        }
    }
}
