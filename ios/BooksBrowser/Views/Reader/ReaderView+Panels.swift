import SwiftUI
import ReadiumShared

extension ReaderView {
    var vocabularyContext: ReaderVocabularyContext {
        ReaderVocabularyContext(
            vocabulary: allVocabulary,
            modelContext: modelContext,
            book: book,
            currentLocator: currentLocator,
            notebookId: book.resolvedNotebookId
        )
    }

    var initialLocator: Locator? {
        guard let json = book.lastReadLocatorJSON else { return nil }
        return try? Locator(jsonString: json)
    }

    @ViewBuilder
    var readerMainContent: some View {
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
            readerErrorState(error)
        }
    }

    func readerErrorState(_ error: String) -> some View {
        ScrollView {
            VStack {
                Spacer(minLength: ReaderPresentationMetrics.Preview.topInset)

                AppEmptyStateCard(
                    title: "無法開啟書籍".localized,
                    systemImage: "exclamationmark.triangle",
                    description: error
                )
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

                Spacer(minLength: ReaderPresentationMetrics.Preview.bottomInset)
            }
            .frame(maxWidth: .infinity)
        }
        .background(viewConfiguration.paperColor.ignoresSafeArea())
    }

    @ViewBuilder
    var settingsPanelContent: some View {
        ReaderSettingsPanel(
            settings: settings,
            onDismiss: {
                closeOverlay(.settings)
            }
        )
    }

    @ViewBuilder
    var translationPanelContent: some View {
        if let selection = handler.wordSelection {
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
                onShowDetail: {
                    let entry = vocabularyContext.existingEntry(matching: selection.word)
                    return entry != nil ? { readerState.detailEntry = entry } : nil
                }(),
                onDismiss: {
                    handler.dismiss()
                    closeOverlay(.translation)
                }
            )
        }
    }
}
