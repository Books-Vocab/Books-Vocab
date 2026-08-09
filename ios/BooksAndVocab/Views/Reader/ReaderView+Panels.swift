#if os(iOS)
import SwiftUI
import ReadiumShared

extension ReaderView {
    var vocabularyContext: ReaderVocabularyContext {
        ReaderVocabularyContext(
            vocabulary: allVocabulary,
            modelContext: modelContext,
            book: book,
            currentLocator: currentLocator,
            notebookId: book.resolvedNotebookId,
            toastCoordinator: toastCoordinator
        )
    }

    var initialLocator: Locator? {
        guard let json = book.lastReadLocatorJSON else { return nil }
        do {
            return try Locator(jsonString: json)
        } catch {
            AppLog.reader.error("Failed to restore saved locator: \(error.localizedDescription, privacy: .public)")
            return nil
        }
    }

    @ViewBuilder
    var readerMainContent: some View {
        if let publication {
            ReadiumNavigatorView(
                publication: publication,
                initialLocator: initialLocator,
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
            readerErrorState(error)
        }
    }

    func readerErrorState(_ error: String) -> some View {
        let presentation = readerErrorPresentation(for: error)
        return ScrollView {
            VStack {
                Spacer(minLength: ReaderPresentationMetrics.Preview.topInset)

                AppEmptyStateCard(
                    title: presentation.title,
                    systemImage: presentation.systemImage,
                    description: presentation.description,
                    action: AppEmptyStateAction(
                        title: "重試載入".localized,
                        systemImage: "arrow.clockwise",
                        handler: { retryLoadPublication() }
                    )
                )
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

                Spacer(minLength: ReaderPresentationMetrics.Preview.bottomInset)
            }
            .frame(maxWidth: .infinity)
        }
        .background(viewConfiguration.paperColor.ignoresSafeArea())
    }

    /// 根據錯誤訊息與當前網路狀態，挑選合適的圖示／標題／敘述。
    /// 不解析後端錯誤碼，僅作字串啟發式分類，足以服務「等 iCloud / 離線 / 一般失敗」三種主場景。
    private func readerErrorPresentation(for error: String) -> ReaderErrorPresentation {
        let offline = !NetworkMonitor.shared.isConnected
        let lower = error.lowercased()
        if lower.contains("icloud") {
            return ReaderErrorPresentation(
                title: "iCloud 下載失敗".localized,
                systemImage: "icloud.slash",
                description: error
            )
        }
        if offline || lower.contains("offline") || lower.contains("internet") || lower.contains("network") {
            return ReaderErrorPresentation(
                title: "目前無法連線".localized,
                systemImage: "wifi.slash",
                description: "請確認網路或 iCloud 同步狀態後再試一次。\n\n".localized + error
            )
        }
        return ReaderErrorPresentation(
            title: "無法開啟書籍".localized,
            systemImage: "exclamationmark.triangle",
            description: error
        )
    }

    @ViewBuilder
    var settingsPanelContent: some View {
        ReaderSettingsPanel(
            settings: settings,
            onDismiss: {
                closeOverlay(.settings)
            }
        )
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    @ViewBuilder
    var translationPanelContent: some View {
        if let selection = handler.wordSelection {
            // 快取一次詞庫查找，避免 body 重算時 existingEntry() 在 nil 檢查與
            // closure 內各掃一次（1000+ 詞庫下為 O(n)×2 線性掃 + lowercased）。
            let existingDetailEntry = vocabularyContext.existingEntry(matching: selection.word)
            makeTranslationPanel(selection: selection, existingDetailEntry: existingDetailEntry)
        }
    }

    private func makeTranslationPanel(selection: WordSelection, existingDetailEntry: VocabularyEntry?) -> some View {
        TranslationPanel(
                word: selection.word,
                result: handler.translationResult,
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
                onShowDetail: existingDetailEntry != nil ? {
                    if let entry = existingDetailEntry {
                        readerState.detailEntry = entry
                    }
                } : nil,
                onDismiss: {
                    handler.dismiss()
                    closeOverlay(.translation)
                },
                onLogin: authManager.isLoggedIn ? nil : { loginGate.presentLogin() },
                onRetryTranslation: (handler.translationErrorMessage != nil && handler.lastLookup != nil)
                    ? { handler.retryLastLookup(vocabularyContext: vocabularyContext) }
                    : nil,
                onRetryExplanation: (handler.explanationErrorMessage != nil && handler.lastLookup != nil)
                    ? { handler.retryLastLookup(vocabularyContext: vocabularyContext) }
                    : nil,
                isPanelLarge: handler.isPanelLarge,
                onToggleHeight: { handler.togglePanelHeight() }
        )
    }
}

/// Reader 載入失敗時，UI 呈現所需的 三元組（title / 圖示 / 敘述）。
struct ReaderErrorPresentation {
    let title: String
    let systemImage: String
    let description: String
}
#endif
