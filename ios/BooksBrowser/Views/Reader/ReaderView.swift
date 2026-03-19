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
    @Environment(\.modelContext) var modelContext
    @Environment(\.dismiss) private var dismiss
    @Environment(\.readiumService) var readiumService
    @Environment(\.iCloudDownloadManager) private var downloadManager
    // PERF: 詞彙量超過 5000 時考慮改為按書篩選
    @Query(
        filter: #Predicate<VocabularyEntry> { $0.actionType != "delete" }
    )
    var allVocabulary: [VocabularyEntry]  // 全域生詞（跨書）

    @State var publication: Publication?
    @State var readerState = ReaderViewState()

    // 翻譯 handler（封裝所有翻譯狀態與詞庫邏輯）
    @State var handler = ReaderTranslationHandler()

    // 觸發導航
    @State var navigateToLocator: (locator: Locator, id: UUID)? = nil

    // 進度
    @State var currentLocator: Locator?
    @State var totalProgression: Double = 0

    // 閱讀殼層狀態：集中 header / overlay / blocker 的控制面
    @State var chromeState = ReaderChromeState()

    // 單字本選擇
    @State private var showNotebookPicker = false

    @Environment(\.kgService) private var kgService
    @Environment(\.authManager) var authManager
    @Environment(\.subscriptionManager) private var subscriptionManager
    @Environment(\.readerSettings) var settings

    @Environment(\.colorScheme) private var colorScheme

    var viewConfiguration: ReaderViewConfiguration {
        settings.viewConfiguration(systemColorScheme: colorScheme)
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
            onShowNotebookPicker: { showNotebookPicker = true },
            onExpandHeader: expandHeader,
            onCollapseHeader: collapseHeader
        ) {
            readerMainContent
        } translationPanel: {
            translationPanelContent
        } settingsPanel: {
            settingsPanelContent
        }
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
            .appSheet(.adaptive)
            .presentationBackground(.ultraThinMaterial)
        }
        .sheet(isPresented: Binding(get: { readerState.showSubscriptionPaywall }, set: { readerState.showSubscriptionPaywall = $0 })) {
            SubscriptionPaywallSheet()
        }
        .sheet(item: Binding(get: { readerState.detailEntry }, set: { readerState.detailEntry = $0 })) { entry in
            WordDetailSheet(entry: entry, allEntries: allVocabulary)
        }
        .sheet(isPresented: $showNotebookPicker) {
            ReaderNotebookPicker(book: book)
                .appSheet(.adaptive)
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

    // MARK: - 載入 Publication

    private func loadPublication() async {
        do {
            let loader = ReaderPublicationLoader(
                readiumService: readiumService,
                downloadManager: downloadManager
            )
            let result = try await loader.loadPublication(for: book) { phase in
                readerState.loadingPhase = phase
            }
            await MainActor.run {
                publication = result.publication
                readerState.isLoading = false
                handler.loadLookedUpWords(from: allVocabulary)
            }

            Task {
                let uniqueWords = await result.uniqueWordsTask.value
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
}
