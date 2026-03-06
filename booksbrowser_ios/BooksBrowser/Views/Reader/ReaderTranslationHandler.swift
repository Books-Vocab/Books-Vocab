//
//  ReaderTranslationHandler.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/3/1.
//

import SwiftUI
import SwiftData
import ReadiumShared

/// 封裝閱讀器全部翻譯狀態與詞庫邏輯，由 ReaderView 持有並橋接
@Observable
final class ReaderTranslationHandler {

    // MARK: - 翻譯狀態
    var wordSelection: WordSelection?
    var translationResult: TranslationResult?
    var pronunciation: String?
    var isTranslating = false
    var showTranslationPanel = false
    var isSaved = false
    var isExpanded = false
    var explanationText: String?
    var isLoadingExplanation = false
    var translationStatus: String?
    var explanationStatus: String?

    // MARK: - 底線觸發信號
    var lookedUpWords: [String] = []
    var bookUniqueWords: Set<String>? = nil
    var clearHighlightTrigger = UUID()
    var removeWordTrigger: (word: String, id: UUID)? = nil

    // MARK: - 計算屬性
    var statusMessage: String? { translationStatus ?? explanationStatus }
    var isExplanationOnly: Bool { wordSelection != nil && translationResult == nil && isExpanded }

    // MARK: - 私有服務（protocol 類型，方便測試時注入 mock）
    private let translationService: any Translating
    private let authManager: any AuthManaging

    // 取消前一次未完成的翻譯 task（快速連點防覆蓋）
    private var currentTranslationTask: Task<Void, Never>?

    init(
        translationService: any Translating = TranslationService(),
        authManager: any AuthManaging = AuthManager.shared
    ) {
        self.translationService = translationService
        self.authManager = authManager
    }

    // MARK: - Flow 1: 單字選取

    func handleWordSelected(
        word: String,
        context: String,
        vocabulary: [VocabularyEntry],
        modelContext: ModelContext,
        book: Book,
        currentLocator: Locator?
    ) {
        let normalizedWord = normalizeWord(word)
        let selection = WordSelection(word: normalizedWord, context: context, position: .zero)
        wordSelection = selection

        // 先查本地生詞庫（含 inflections / rootForm 匹配）
        let wordLower = word.lowercased()
        if let existing = vocabulary.first(where: { entry in
            let w = entry.word.lowercased()
            if w == wordLower { return true }
            if entry.rootForm?.lowercased() == wordLower { return true }
            return entry.inflections.contains { $0.lowercased() == wordLower }
        }) {
            withAnimation(.spring(response: 0.3)) {
                translationResult = TranslationResult(
                    translation: existing.translation,
                    partOfSpeech: nil,
                    pronunciation: nil,
                    explanation: nil
                )
                pronunciation = existing.pronunciation
                isSaved = true
                isTranslating = false
                showTranslationPanel = true
                isExpanded = false
                explanationText = nil
            }
            print("📦 從生詞庫載入: \(word) → \(existing.word)")
            return
        }

        if !authManager.isLoggedIn {
            withAnimation(.spring(response: 0.3)) {
                showTranslationPanel = true
                isTranslating = false
                translationResult = nil
                isSaved = false
                isExpanded = false
                explanationText = nil
            }
            Task {
                let fetchedPron = await DictionaryService.fetchPronunciation(word: word)
                await MainActor.run {
                    self.pronunciation = fetchedPron
                    guestSaveToVocabulary(
                        selection: selection,
                        pronunciation: fetchedPron,
                        vocabulary: vocabulary,
                        modelContext: modelContext,
                        book: book,
                        currentLocator: currentLocator
                    )
                }
            }
            return
        }

        withAnimation(.spring(response: 0.3)) {
            showTranslationPanel = true
            isTranslating = true
            translationResult = nil
            pronunciation = nil
            isSaved = false
            isExpanded = false
            explanationText = nil
        }

        currentTranslationTask?.cancel()
        currentTranslationTask = Task {
            let translationTask = Task {
                try await translationService.translateQuick(
                    word: word,
                    context: context,
                    onRetry: { attempt, total in
                        Task { @MainActor in
                            self.translationStatus = "正在重試 (\(attempt)/\(total))..."
                        }
                    }
                )
            }

            let pronTask = Task {
                await DictionaryService.fetchPronunciation(word: word)
            }

            do {
                let result = try await translationTask.value
                await MainActor.run {
                    withAnimation {
                        translationResult = result
                        isTranslating = false
                        translationStatus = nil
                    }
                }

                let fetchedPron = await pronTask.value
                await MainActor.run {
                    withAnimation {
                        pronunciation = fetchedPron
                    }
                    if let sel = wordSelection {
                        autoSaveToVocabulary(
                            selection: sel,
                            result: result,
                            pronunciation: fetchedPron,
                            vocabulary: vocabulary,
                            modelContext: modelContext,
                            book: book,
                            currentLocator: currentLocator
                        )
                    }
                }
            } catch {
                guard !(error is CancellationError) else { return }
                print("❌ 翻譯錯誤: \(error)")
                let fetchedPron = await pronTask.value
                await MainActor.run {
                    translationResult = TranslationResult(
                        translation: "翻譯失敗：\(error.localizedDescription)",
                        partOfSpeech: nil,
                        pronunciation: nil,
                        explanation: nil
                    )
                    pronunciation = fetchedPron
                    isTranslating = false
                    translationStatus = nil
                }
            }
        }
    }

    // MARK: - Flow 2: 短語翻譯

    func handlePhraseSelected(
        phrase: String,
        context: String,
        vocabulary: [VocabularyEntry],
        modelContext: ModelContext,
        book: Book,
        currentLocator: Locator?
    ) {
        let selection = WordSelection(word: phrase, context: context, position: .zero)
        wordSelection = selection

        withAnimation(.spring(response: 0.3)) {
            showTranslationPanel = true
            isTranslating = true
            translationResult = nil
            pronunciation = nil
            isSaved = false
            isExpanded = false
            explanationText = nil
        }

        Task {
            do {
                let translation = try await translationService.translatePhrase(
                    phrase: phrase,
                    context: context,
                    onRetry: { attempt, total in
                        Task { @MainActor in self.translationStatus = "正在重試 (\(attempt)/\(total))..." }
                    }
                )
                await MainActor.run {
                    withAnimation {
                        translationResult = TranslationResult(
                            translation: translation,
                            partOfSpeech: nil,
                            pronunciation: nil,
                            explanation: nil
                        )
                        isTranslating = false
                        translationStatus = nil
                    }
                    if let result = translationResult {
                        autoSaveToVocabulary(
                            selection: selection,
                            result: result,
                            pronunciation: nil,
                            vocabulary: vocabulary,
                            modelContext: modelContext,
                            book: book,
                            currentLocator: currentLocator
                        )
                    }
                }
            } catch {
                await MainActor.run {
                    translationResult = TranslationResult(
                        translation: "翻譯失敗：\(error.localizedDescription)",
                        partOfSpeech: nil, pronunciation: nil, explanation: nil
                    )
                    isTranslating = false
                    translationStatus = nil
                }
            }
        }
    }

    // MARK: - Flow 3: 語境解釋（不存入詞庫）

    func handleExplainSelected(text: String, context: String) {
        let selection = WordSelection(word: text, context: context, position: .zero)
        wordSelection = selection

        withAnimation(.spring(response: 0.3)) {
            showTranslationPanel = true
            isTranslating = false
            translationResult = nil
            pronunciation = nil
            isSaved = false
            isExpanded = true
            isLoadingExplanation = true
            explanationText = nil
        }

        Task {
            do {
                let (explanation, _) = try await translationService.fetchExplanation(
                    word: text,
                    context: context,
                    onRetry: { attempt, total in
                        Task { @MainActor in self.explanationStatus = "正在重試 (\(attempt)/\(total))..." }
                    }
                )
                await MainActor.run {
                    withAnimation {
                        explanationText = explanation
                        isLoadingExplanation = false
                        explanationStatus = nil
                    }
                }
            } catch {
                await MainActor.run {
                    explanationText = "載入失敗：\(error.localizedDescription)"
                    isLoadingExplanation = false
                    explanationStatus = nil
                }
            }
        }
    }

    // MARK: - Phase 2: 展開/收合解釋

    func handleExpand() {
        withAnimation(.spring(response: 0.3)) {
            isExpanded.toggle()
        }

        guard authManager.isLoggedIn, isExpanded, !isLoadingExplanation,
              let selection = wordSelection else { return }

        explanationText = nil
        isLoadingExplanation = true
        explanationStatus = nil

        Task {
            do {
                let (explanation, latency) = try await translationService.fetchExplanation(
                    word: selection.word,
                    context: selection.context,
                    onRetry: { attempt, total in
                        self.explanationStatus = "正在重試 (\(attempt)/\(total))..."
                    }
                )
                await MainActor.run {
                    withAnimation {
                        explanationText = explanation
                        isLoadingExplanation = false
                        explanationStatus = nil
                        if var updatedResult = translationResult {
                            updatedResult.latency = latency
                            translationResult = updatedResult
                        }
                    }
                }
            } catch {
                print("❌ 解釋錯誤: \(error)")
                await MainActor.run {
                    explanationText = "載入失敗：\(error.localizedDescription)"
                    isLoadingExplanation = false
                    explanationStatus = nil
                }
            }
        }
    }

    // MARK: - 從生詞庫刪除

    func deleteFromVocabulary(_ word: String, vocabulary: [VocabularyEntry], modelContext: ModelContext) {
        let wordLower = word.lowercased()
        if let entry = vocabulary.first(where: { entry in
            let w = entry.word.lowercased()
            if w == wordLower { return true }
            if entry.rootForm?.lowercased() == wordLower { return true }
            return entry.inflections.contains { $0.lowercased() == wordLower }
        }) {
            if entry.syncStatus == 1 {
                entry.actionType = "delete"
                entry.syncStatus = 0
                print("🗑️ Queued KG delete action for: \(word)")
            } else {
                modelContext.delete(entry)
                print("🗑️ Deleted local entry: \(word)")
            }
            try? modelContext.save()
        }
        dismiss()
    }

    // MARK: - 載入已查詞

    func loadLookedUpWords(from vocabulary: [VocabularyEntry]) {
        lookedUpWords = vocabulary.flatMap { entry in
            var all = Set([entry.word.lowercased()] + entry.inflections.map { $0.lowercased() })
            if let root = entry.rootForm?.lowercased() { all.insert(root) }
            return Array(all)
        }
    }

    // MARK: - 關閉面板

    func dismiss() {
        withAnimation(.spring(response: 0.3)) {
            showTranslationPanel = false
            wordSelection = nil
            translationResult = nil
            pronunciation = nil
            isSaved = false
            isExpanded = false
            explanationText = nil
        }
        clearHighlightTrigger = UUID()
    }

    // MARK: - 私有方法

    @MainActor
    private func autoSaveToVocabulary(
        selection: WordSelection,
        result: TranslationResult,
        pronunciation: String?,
        vocabulary: [VocabularyEntry],
        modelContext: ModelContext,
        book: Book,
        currentLocator: Locator?
    ) {
        let wordLower = selection.word.lowercased()
        let alreadyExists = vocabulary.contains { $0.word.lowercased() == wordLower }
        guard !alreadyExists else {
            if !lookedUpWords.contains(wordLower) {
                lookedUpWords.append(wordLower)
            }
            withAnimation { isSaved = true }
            return
        }

        let entry = VocabularyEntry(
            word: selection.word,
            translation: result.translation,
            context: selection.context,
            explanation: nil,
            partOfSpeech: nil,
            pronunciation: pronunciation,
            bookTitle: book.title,
            chapterTitle: currentLocator?.title
        )
        entry.rootForm = result.rootForm
        entry.book = book
        modelContext.insert(entry)
        try? modelContext.save()

        if !lookedUpWords.contains(wordLower) {
            lookedUpWords.append(wordLower)
        }
        withAnimation { isSaved = true }
        print("✅ Auto-saved: \(selection.word)")
    }

    @MainActor
    private func guestSaveToVocabulary(
        selection: WordSelection,
        pronunciation: String?,
        vocabulary: [VocabularyEntry],
        modelContext: ModelContext,
        book: Book,
        currentLocator: Locator?
    ) {
        let wordLower = selection.word.lowercased()
        let alreadyExists = vocabulary.contains { $0.word.lowercased() == wordLower }
        guard !alreadyExists else {
            if !lookedUpWords.contains(wordLower) { lookedUpWords.append(wordLower) }
            withAnimation { isSaved = true }
            return
        }

        let entry = VocabularyEntry(
            word: selection.word,
            translation: "",
            context: selection.context,
            explanation: nil,
            partOfSpeech: nil,
            pronunciation: pronunciation,
            bookTitle: book.title,
            chapterTitle: currentLocator?.title
        )
        entry.book = book
        modelContext.insert(entry)
        try? modelContext.save()

        if !lookedUpWords.contains(wordLower) { lookedUpWords.append(wordLower) }
        withAnimation { isSaved = true }
        print("✅ Guest saved: \(selection.word)")
    }

    private func normalizeWord(_ word: String) -> String {
        word.precomposedStringWithCompatibilityMapping
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}
