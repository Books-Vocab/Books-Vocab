#if os(iOS)
//
//  PDFReaderView.swift
//  BooksBrowser
//
//  PDFKit 原生渲染 + 詞彙捕捉整合
//

import SwiftUI
import SwiftData
import PDFKit

// MARK: - Progress Persistence

private struct PDFPosition: Codable {
    let pageIndex: Int
}

// MARK: - PDFReaderView

struct PDFReaderView: View {
    let book: Book

    @Environment(\.modelContext) private var modelContext
    @Environment(\.authManager) private var authManager
    @Environment(\.toastCoordinator) private var toastCoordinator
    @Environment(\.dismiss) private var dismiss

    @Query(
        filter: #Predicate<VocabularyEntry> { $0.actionType != "delete" }
    )
    private var allVocabulary: [VocabularyEntry]

    @State private var pdfDocument: PDFDocument?
    @State private var loadError: String?
    @State private var handler = ReaderTranslationHandler()
    @State private var showTranslation = false
    @State private var showLoginSheet = false

    private var vocabularyContext: ReaderVocabularyContext {
        ReaderVocabularyContext(
            vocabulary: allVocabulary,
            modelContext: modelContext,
            book: book,
            currentLocator: nil,
            notebookId: book.resolvedNotebookId,
            toastCoordinator: toastCoordinator
        )
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            Group {
                if let document = pdfDocument {
                    PDFKitRepresentable(
                        document: document,
                        book: book,
                        modelContext: modelContext,
                        onWordSelected: { word, context in
                            handler.handleWordSelected(
                                word: word,
                                context: context,
                                vocabularyContext: vocabularyContext
                            )
                            withAnimation(AppMotion.panelState) {
                                showTranslation = true
                            }
                        }
                    )
                    .ignoresSafeArea(edges: [.horizontal, .bottom])
                } else if let error = loadError {
                    errorView(error)
                } else {
                    loadingView
                }
            }

            if showTranslation, let selection = handler.wordSelection {
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
                        handler.deleteFromVocabulary(
                            selection.word, context: vocabularyContext
                        )
                        withAnimation(AppMotion.panelState) {
                            showTranslation = false
                        }
                    },
                    onShowDetail: vocabularyContext.existingEntry(matching: selection.word) != nil
                        ? { /* detail navigation not applicable in PDF reader */ }
                        : nil,
                    onDismiss: {
                        handler.dismiss()
                        withAnimation(AppMotion.panelState) {
                            showTranslation = false
                        }
                    },
                    onLogin: authManager.isLoggedIn ? nil : { showLoginSheet = true },
                    onRetryTranslation: (handler.translationErrorMessage != nil && handler.lastLookup != nil)
                        ? { handler.retryLastLookup(vocabularyContext: vocabularyContext) }
                        : nil,
                    onRetryExplanation: (handler.explanationErrorMessage != nil && handler.lastLookup != nil)
                        ? { handler.retryLastLookup(vocabularyContext: vocabularyContext) }
                        : nil
                )
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
                .transition(.readerPanelReveal)
            }
        }
        .task { loadDocument() }
        .navigationBarTitleDisplayMode(.inline)
        .sheet(isPresented: $showLoginSheet) {
            LoginSheet()
        }
    }

    // MARK: - Loading

    private func loadDocument() {
        let url = book.fileURL
        let fm = FileManager.default
        if !fm.isReadableFile(atPath: url.path) {
            // iCloud 占位符 / 未下載：給較具體的提示
            loadError = "PDF 檔案尚未從 iCloud 下載完成或已被移除。請確認檔案可在「檔案」App 中開啟後再試一次。".localized
            AppLog.reader.error("PDF unreadable at: \(url.lastPathComponent)")
            return
        }
        guard let document = PDFDocument(url: url) else {
            loadError = "無法載入 PDF 檔案。檔案可能已損毀，或格式不受支援。".localized
            AppLog.reader.error("PDF load failed: \(url.lastPathComponent)")
            return
        }
        loadError = nil
        pdfDocument = document
    }

    private func retryLoad() {
        loadError = nil
        pdfDocument = nil
        loadDocument()
    }

    // MARK: - State Views

    private var loadingView: some View {
        VStack {
            Spacer()
            ProgressView()
                .scaleEffect(AppMetrics.loadingIndicatorScaleMedium)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func errorView(_ message: String) -> some View {
        ScrollView {
            VStack {
                Spacer(minLength: AppMetrics.spacingExtraLarge)

                AppEmptyStateCard(
                    title: "無法開啟 PDF".localized,
                    systemImage: "exclamationmark.triangle",
                    description: message,
                    action: AppEmptyStateAction(
                        title: "重試載入".localized,
                        systemImage: "arrow.clockwise",
                        handler: retryLoad
                    )
                )
                .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)

                Spacer(minLength: AppMetrics.spacingExtraLarge)
            }
            .frame(maxWidth: .infinity)
        }
    }
}

// MARK: - PDFKitRepresentable

private struct PDFKitRepresentable: UIViewRepresentable {
    let document: PDFDocument
    let book: Book
    let modelContext: ModelContext
    let onWordSelected: (String, String) -> Void

    func makeUIView(context: Context) -> PDFView {
        let pdfView = PDFView()
        pdfView.document = document
        pdfView.displayMode = .singlePageContinuous
        pdfView.autoScales = true
        pdfView.displayDirection = .vertical

        // Restore last read position
        restorePosition(in: pdfView)

        // Page change notification for progress saving
        NotificationCenter.default.addObserver(
            context.coordinator,
            selector: #selector(Coordinator.pageDidChange(_:)),
            name: .PDFViewPageChanged,
            object: pdfView
        )

        // Add edit menu interaction for vocabulary capture
        let menuInteraction = UIEditMenuInteraction(delegate: context.coordinator)
        pdfView.addInteraction(menuInteraction)
        context.coordinator.pdfView = pdfView
        context.coordinator.menuInteraction = menuInteraction

        // Listen for selection changes to show menu
        NotificationCenter.default.addObserver(
            context.coordinator,
            selector: #selector(Coordinator.selectionDidChange(_:)),
            name: .PDFViewSelectionChanged,
            object: pdfView
        )

        return pdfView
    }

    func updateUIView(_ pdfView: PDFView, context: Context) {
        // No dynamic updates needed
    }

    static func dismantleUIView(_ pdfView: PDFView, coordinator: Coordinator) {
        NotificationCenter.default.removeObserver(coordinator)
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(book: book, modelContext: modelContext, onWordSelected: onWordSelected)
    }

    private func restorePosition(in pdfView: PDFView) {
        guard let json = book.lastReadLocatorJSON,
              let data = json.data(using: .utf8),
              let position = try? JSONDecoder().decode(PDFPosition.self, from: data),
              let page = document.page(at: position.pageIndex)
        else { return }
        pdfView.go(to: page)
    }

    // MARK: - Coordinator

    final class Coordinator: NSObject, UIEditMenuInteractionDelegate {
        let book: Book
        let modelContext: ModelContext
        let onWordSelected: (String, String) -> Void
        weak var pdfView: PDFView?
        weak var menuInteraction: UIEditMenuInteraction?

        init(
            book: Book,
            modelContext: ModelContext,
            onWordSelected: @escaping (String, String) -> Void
        ) {
            self.book = book
            self.modelContext = modelContext
            self.onWordSelected = onWordSelected
        }

        // MARK: - Progress Saving

        @objc func pageDidChange(_ notification: Notification) {
            guard let pdfView = notification.object as? PDFView,
                  let currentPage = pdfView.currentPage,
                  let document = pdfView.document,
                  let pageIndex = document.index(for: currentPage) as Int?
            else { return }

            let pageCount = document.pageCount
            guard pageCount > 0 else { return }

            // Encode position
            let position = PDFPosition(pageIndex: pageIndex)
            if let data = try? JSONEncoder().encode(position),
               let json = String(data: data, encoding: .utf8) {
                book.lastReadLocatorJSON = json
            }

            // Progression: 0.0 ~ 1.0
            book.progression = pageCount > 1
                ? Double(pageIndex) / Double(pageCount - 1)
                : 1.0
            book.dateLastRead = Date()

            modelContext.safeSave()
        }

        // MARK: - Selection → Vocabulary

        @objc func selectionDidChange(_ notification: Notification) {
            guard let pdfView = pdfView,
                  let selection = pdfView.currentSelection,
                  let text = selection.string,
                  !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            else { return }

            // Show edit menu near selection
            if let page = selection.pages.first,
               let menuInteraction = menuInteraction {
                let selectionBounds = selection.bounds(for: page)
                let viewRect = pdfView.convert(selectionBounds, from: page)
                let config = UIEditMenuConfiguration(
                    identifier: "vocabMenu" as NSString,
                    sourcePoint: CGPoint(
                        x: viewRect.midX,
                        y: viewRect.minY
                    )
                )
                menuInteraction.presentEditMenu(with: config)
            }
        }

        // MARK: - UIEditMenuInteractionDelegate

        func editMenuInteraction(
            _ interaction: UIEditMenuInteraction,
            menuFor configuration: UIEditMenuConfiguration,
            suggestedActions: [UIMenuElement]
        ) -> UIMenu? {
            let translateAction = UIAction(
                title: "翻譯".localized,
                image: UIImage(systemName: "character.book.closed")
            ) { [weak self] _ in
                self?.triggerWordSelection()
            }

            // Keep system actions (Copy, etc.) and prepend translate
            return UIMenu(children: [translateAction] + suggestedActions)
        }

        private func triggerWordSelection() {
            guard let pdfView = pdfView,
                  let selection = pdfView.currentSelection,
                  let word = selection.string?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !word.isEmpty
            else { return }

            // Extract surrounding context from the page
            let context = extractContext(for: selection, in: pdfView)
            pdfView.clearSelection()

            Task { @MainActor in
                onWordSelected(word, context)
            }
        }

        private func extractContext(
            for selection: PDFSelection,
            in pdfView: PDFView
        ) -> String {
            guard let page = selection.pages.first,
                  let pageText = page.string
            else { return selection.string ?? "" }

            let selectedText = selection.string ?? ""
            guard let range = pageText.range(of: selectedText) else {
                return selectedText
            }

            // ~100 chars around the selection
            let contextRadius = 100
            let start = pageText.index(
                range.lowerBound,
                offsetBy: -contextRadius,
                limitedBy: pageText.startIndex
            ) ?? pageText.startIndex
            let end = pageText.index(
                range.upperBound,
                offsetBy: contextRadius,
                limitedBy: pageText.endIndex
            ) ?? pageText.endIndex

            return String(pageText[start..<end])
                .replacingOccurrences(of: "\n", with: " ")
                .trimmingCharacters(in: .whitespacesAndNewlines)
        }
    }
}

// MARK: - Preview

#Preview("PDF Reader — Loading") {
    AppThemeContainer {
        PDFReaderView(book: .init(title: "Sample PDF", author: "Author", fileName: "sample.pdf", format: .pdf))
            .modelContainer(for: [Book.self, VocabularyEntry.self], inMemory: true)
    }
}
#endif
