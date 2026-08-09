#if os(iOS)
//
//  ReaderView.swift
//  Books & Vocab
//
//  Created by 陳亮宇 on 2026/2/24.
//

import SwiftUI
import SwiftData
import TipKit
import ReadiumShared
import ReadiumNavigator
import os

/// 閱讀器主介面（Readium 版）
struct ReaderView: View {
    @ObserveInjection private var inject
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

    // 用於驗證 book.preferredNotebookId 是否指向仍存在的 notebook
    @Query(filter: #Predicate<Notebook> { !$0.isSoftDeleted })
    private var liveNotebooks: [Notebook]

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
    @State var loginGate = LoginGateState()
    /// retry 重新載入的 in-flight handle。`.task` 走結構化作用域隨 view 自動取消，
    /// 但 retry 是手動觸發的非結構化 Task — 持 handle 以便 onDisappear 一併取消，
    /// 否則 retry 載入中途 dismiss 仍會 fire-and-forget 寫回已棄置的 handler。
    @State private var retryLoadTask: Task<Void, Never>?

    @Environment(\.authManager) var authManager
    @Environment(\.toastCoordinator) var toastCoordinator
    @Environment(\.readerSettings) var settings

    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.scenePhase) private var scenePhase

    /// EPUB 翻頁進度落盤器：in-memory 寫入立即、`save()` debounce coalesce，
    /// `onDisappear` / scenePhase `.background` 兜底 flush。對齊 PDF 路徑的顯式 save。
    @State var progressSaver = ReaderProgressSaver()

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
        }
        // 閱讀設定改由系統 sheet 呈現（APP-20260808-240a94）：detents 與
        // drag indicator 由平台提供，取代原本自繪的底部 overlay 卡片 + handle。
        // `appAppearanceScheme()`：這一頁的主題選擇器寫的是**整個 app** 的外觀，
        // 而 sheet 呈現後不會再跟著 root 換 —— 少了它，選深色的當下原生 Form 會
        // 留在淺色，section header 直接消失（APP-20260809-f1b8cb）。
        .sheet(isPresented: isReaderSettingsPresented) {
            settingsPanelContent.appAppearanceScheme()
        }
        .safeAreaInset(edge: .top) {
            TipView(LongPressTip())
                .padding(.horizontal)
        }
        .tint(.secondary)
        .toolbar(.hidden, for: .tabBar)
        .toolbar(.hidden, for: .navigationBar)
        .macReaderImmersion()
        .toastSheet(isPresented: Binding(get: { readerState.showTableOfContents }, set: { readerState.showTableOfContents = $0 })) {
            tableOfContentsSheet
        }
        .task {
            sanitizeStaleBoundNotebook()
            seedNotebookBindingIfNeeded()
            await loadPublication()
        }
        .onDisappear {
            // dismiss / pop 時取消 in-flight 翻譯 task，避免網路 Task
            // 續跑到完成後寫回已棄置的 handler（多餘網路/寫入）。
            // 用 onDisappear 而非 @MainActor @Observable 的 deinit
            // （時序與 actor 隔離易出錯）。
            handler.cancelCurrentTranslationTask()
            // retry 走非結構化 Task，不隨 view 生命週期自動取消 —
            // 在此一併取消其 in-flight extractUniqueWords，避免寫回已棄置的 handler。
            retryLoadTask?.cancel()
            // dismiss / pop 時若 debounce 窗口未到期，flush 最後一次翻頁進度，
            // 避免 debounce 反而丟最後位置。
            progressSaver.flush()
        }
        .onChange(of: scenePhase) { _, newPhase in
            // 退背景時 flush debounced 進度，覆蓋正常退出路徑；僅前景強殺極端
            // case 會丟失 debounce 窗口內的最後翻頁（對齊 CloudPreferencesSync 兜底）。
            if newPhase == .background { progressSaver.flush() }
        }
        .onChange(of: liveNotebooks.map(\.remoteId)) { _, _ in
            sanitizeStaleBoundNotebook()
            // notebooks settle 後補 seed：.task 當下 liveNotebooks 可能尚未 settle 而跳過。
            seedNotebookBindingIfNeeded()
        }
        .onChange(of: VocabularyHighlightSignature.make(
            entries: allVocabulary,
            notebookId: book.resolvedNotebookId
        )) { _, _ in
            handler.loadLookedUpWords(
                from: allVocabulary,
                notebookId: book.resolvedNotebookId
            )
        }
        .onChange(of: book.resolvedNotebookId) { _, notebookId in
            handler.loadLookedUpWords(
                from: allVocabulary,
                notebookId: notebookId
            )
        }
        .onChange(of: authManager.isLoggedIn) { _, loggedIn in
            // 登出時立刻清空底線，不等 SwiftData async clear 通知
            if !loggedIn {
                handler.lookedUpWords = []
                handler.bookUniqueWords = nil
                handler.clearHighlightTrigger = UUID()
            }
        }
        .subscriptionPaywallSheet(isPresented: Binding(get: { readerState.showSubscriptionPaywall }, set: { readerState.showSubscriptionPaywall = $0 }))
        .toastSheet(item: Binding(get: { readerState.detailEntry }, set: { readerState.detailEntry = $0 })) { entry in
            WordDetailSheet(entry: entry, allEntries: allVocabulary)
        }
        .toastSheet(isPresented: $showNotebookPicker) {
            ReaderNotebookPicker(book: book)
                .appSheet(.adaptive)
        }
        .loginGateSheet($loginGate)
        .enableInjection()
    }

    /// `chromeState.overlay` 仍是唯一真相（swipe-to-dismiss / 選字 teardown 都走
    /// `closeOverlay(.settings)`），這裡只是把它投影成系統 sheet 要的 `Bool` binding。
    private var isReaderSettingsPresented: Binding<Bool> {
        Binding(
            get: { chromeState.overlay == .settings },
            set: { isPresented in
                if !isPresented { closeOverlay(.settings) }
            }
        )
    }

    @ViewBuilder private var tableOfContentsSheet: some View {
        if let publication {
            TOCView(
                publication: publication,
                onSelect: { link in handleTOCSelection(link, in: publication) }
            )
        }
    }

    private func handleTOCSelection(_ link: ReadiumShared.Link, in publication: Publication) {
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

    /// 若 book.preferredNotebookId 指向已刪除或不存在的 notebook，清除綁定以避免新單字存入孤兒 notebook。
    /// 空列表代表 @Query 尚未 settle（首次啟動 / 剛登入）— 不清 bound，避免誤清仍合法的遠端 notebook。
    private func sanitizeStaleBoundNotebook() {
        guard let boundId = book.preferredNotebookId else { return }
        guard !liveNotebooks.isEmpty else { return }
        if !liveNotebooks.contains(where: { $0.remoteId == boundId }) {
            book.preferredNotebookId = nil
        }
    }

    /// 強制綁定 seed：書未綁定時（新書 / 剛被 sanitize 清掉 stale 綁定）以最近使用的
    /// 真實單字本（全域 active）固化綁定並持久化。固化後此書的 highlight / 查詢 / autoSave
    /// scope 一律認綁定本、不再隨全域 active 漂移（決策 B：種子綁定 + 之後 picker 乾淨切換）。
    private func seedNotebookBindingIfNeeded() {
        guard book.preferredNotebookId == nil else { return }
        let seed = ActiveNotebookStore.shared.activeNotebookId
        // 只在 seed 指向已 settle 的真實 notebook 時固化，避免凍結離線占位 / 未同步的
        // sentinel；liveNotebooks 尚未 settle 時跳過，待 settle 的 onChange 再 seed。
        guard Book.canSeedBinding(
            seed: seed,
            liveNotebookIds: Set(liveNotebooks.map(\.remoteId))
        ) else { return }
        book.ensureBoundNotebook(seed: seed)
        if modelContext.safeSave() {
            BookManifestStore().writeBestEffort(book: book)
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
            bookTitle: book.title
        )
    }

    // MARK: - 載入 Publication

    /// 從錯誤狀態回到 loading 並重新呼叫 `loadPublication()`。
    /// 在 error overlay 上的「重試載入」按鈕觸發。
    func retryLoadPublication() {
        readerState.errorMessage = nil
        readerState.isLoading = true
        readerState.isWebViewReady = false
        readerState.loadingPhase = L10n.string("開啟書本…")
        // 持 handle：retry 為非結構化 Task，需 onDisappear 顯式取消（見 retryLoadTask 宣告）。
        // 重入先取消舊 retry，避免連點時舊 in-flight 載入洩漏（與 onDisappear 對稱）。
        retryLoadTask?.cancel()
        retryLoadTask = Task { await loadPublication() }
    }

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
                PerfLog.reader.mark("reader.opened", "title=\(book.title)")
                handler.loadLookedUpWords(
                    from: allVocabulary,
                    notebookId: book.resolvedNotebookId
                )
            }

            // 收進 `.task` 結構化作用域：擷取在同一 async 流程內 `await`，
            // 隨 view 生命週期自動取消，不再 fire-and-forget。
            // dismiss 中途離開時整條鏈一併取消，避免寫回已棄置的 handler。
            let uniqueWords = await result.extractUniqueWords()
            // cancel 後（dismiss 中途離開 / retry 被 onDisappear 取消）不寫回已棄置的 handler。
            guard !Task.isCancelled else { return }
            handler.bookUniqueWords = uniqueWords
        } catch {
            AppLog.reader.error("Publication load failed (book=\(book.title)): \(error.localizedDescription, privacy: .public)")
            await MainActor.run {
                readerState.errorMessage = error.localizedDescription
                readerState.isLoading = false
                readerState.isWebViewReady = true  // 顯示錯誤畫面
            }
        }
    }
}
#endif
