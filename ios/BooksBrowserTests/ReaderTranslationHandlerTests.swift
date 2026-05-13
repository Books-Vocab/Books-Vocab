#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksBrowser

/// Behavior tests for `ReaderTranslationHandler` — exercising the synchronous
/// helpers (`autoSaveToVocabulary`, `guestSaveToVocabulary`, `normalizeWord`,
/// `deleteFromVocabulary`) and the async `handleWordSelected` flow with an
/// injected mock service. The async paths are awaited via the handler's
/// `currentTranslationTask` so assertions run after the task settles.
@MainActor
struct ReaderTranslationHandlerTests {

    // MARK: - Mocks

    private final class MockTranslating: Translating {
        var quickResult: Result<TranslationResult, Error> = .failure(MockError.notConfigured)
        var phraseResult: Result<String, Error> = .failure(MockError.notConfigured)
        var explanationResult: Result<(String, TimeInterval), Error> = .failure(MockError.notConfigured)
        var quickCalls = 0
        var phraseCalls = 0
        var explanationCalls = 0

        func translateQuick(word: String, context: String, onRetry: ((Int, Int) -> Void)?) async throws -> TranslationResult {
            quickCalls += 1
            return try quickResult.get()
        }
        func translatePhrase(phrase: String, context: String, onRetry: ((Int, Int) -> Void)?) async throws -> String {
            phraseCalls += 1
            return try phraseResult.get()
        }
        func fetchExplanation(word: String, context: String, onRetry: ((Int, Int) -> Void)?) async throws -> (explanation: String, latency: TimeInterval) {
            explanationCalls += 1
            return try explanationResult.get()
        }
    }

    @MainActor
    private final class MockAuth: AuthManaging {
        var isLoggedIn: Bool
        init(isLoggedIn: Bool) { self.isLoggedIn = isLoggedIn }

        var userId: String? = nil
        var token: String? = nil
        var displayName: String? = nil
        var userEmail: String? = nil
        var avatarURL: URL? = nil
        var authError: String? = nil
        var isAuthenticating: Bool = false
        var isDemoMode: Bool = false

        func enterDemoMode(modelContainer: ModelContainer) {}
        func exitDemoMode(modelContainer: ModelContainer) {}
        func login(userId: String, token: String) {}
        func login(customToken: String) {}
        func logout(modelContainer: ModelContainer?, reason: String) {}
        func loginWithGoogle(modelContainer: ModelContainer?) {}
        func loginWithApple(modelContainer: ModelContainer?) {}
    }

    @MainActor
    private final class MockVocabContext: VocabularyContextProtocol {
        var notebookId: String = "test_nb"
        var existing: VocabularyEntry?
        var savedSelections: [WordSelection] = []
        var savedTranslations: [String] = []
        var savedRootForms: [String?] = []
        var deletedWords: [String] = []
        var saveReturn: Bool = true

        func existingEntry(matching word: String) -> VocabularyEntry? { existing }
        func deleteEntry(matching word: String) { deletedWords.append(word) }
        func saveEntry(selection: WordSelection, translation: String, rootForm: String?) -> Bool {
            savedSelections.append(selection)
            savedTranslations.append(translation)
            savedRootForms.append(rootForm)
            return saveReturn
        }
    }

    private enum MockError: Error, LocalizedError {
        case notConfigured
        case canned(String)
        var errorDescription: String? {
            switch self {
            case .notConfigured: return "mock not configured"
            case .canned(let s): return s
            }
        }
    }

    // MARK: - Helpers

    private func makeHandler(loggedIn: Bool = true, service: MockTranslating = MockTranslating()) -> ReaderTranslationHandler {
        ReaderTranslationHandler(
            translationService: service,
            authManager: MockAuth(isLoggedIn: loggedIn)
        )
    }

    /// Drives the handler's most-recent in-flight task to completion before
    /// asserting. Returns once the task has finished (or immediately if none).
    private func drain(_ handler: ReaderTranslationHandler) async {
        await handler.currentTranslationTask?.value
    }

    // MARK: - normalizeWord

    @Test func normalizeWord_trimsWhitespaceAndPrecomposesCompat() {
        let handler = makeHandler()
        #expect(handler.normalizeWord("  hello  ") == "hello")
        #expect(handler.normalizeWord("\nworld\t") == "world")
        // ﬃ (U+FB03) precomposes/decomposes to "ffi" under compatibility mapping.
        #expect(handler.normalizeWord("oﬃce") == "office")
    }

    // MARK: - autoSaveToVocabulary

    @Test func autoSaveToVocabulary_skipsSaveWhenEntryExistsAndNotDeleted() {
        let handler = makeHandler()
        let ctx = MockVocabContext()
        ctx.existing = VocabularyEntry(
            word: "alpha",
            translation: "已存在",
            context: "",
            explanation: nil,
            partOfSpeech: nil,
            bookTitle: "B",
            chapterTitle: "C"
        )

        handler.autoSaveToVocabulary(
            selection: WordSelection(word: "alpha", context: "ctx", position: .zero),
            result: TranslationResult(translation: "new", partOfSpeech: nil, explanation: nil),
            context: ctx
        )

        #expect(ctx.savedSelections.isEmpty, "existing non-deleted entry must NOT trigger another save")
        #expect(handler.isSaved == true)
        #expect(handler.lookedUpWords.contains("alpha"), "even on existing entry, the word should be tracked as looked-up")
    }

    @Test func autoSaveToVocabulary_callsSaveWhenNoExisting_andRecordsRootForm() {
        let handler = makeHandler()
        let ctx = MockVocabContext()
        var result = TranslationResult(translation: "新", partOfSpeech: nil, explanation: nil)
        result.rootForm = "rooted"

        handler.autoSaveToVocabulary(
            selection: WordSelection(word: "Beta", context: "ctx", position: .zero),
            result: result,
            context: ctx
        )

        #expect(ctx.savedSelections.count == 1)
        #expect(ctx.savedTranslations.first == "新")
        #expect(ctx.savedRootForms.first == "rooted")
        #expect(handler.isSaved == true)
        #expect(handler.lookedUpWords.contains("beta"), "looked-up tracking must be lowercased")
    }

    // MARK: - guestSaveToVocabulary

    @Test func guestSaveToVocabulary_passesEmptyTranslationAndMarksSaved() {
        let handler = makeHandler(loggedIn: false)
        let ctx = MockVocabContext()
        handler.guestSaveToVocabulary(
            selection: WordSelection(word: "gamma", context: "ctx", position: .zero),
            context: ctx
        )
        #expect(ctx.savedSelections.count == 1)
        #expect(ctx.savedTranslations.first == "", "guest path must save with empty translation — server fills it on login")
        #expect(handler.isSaved == true)
    }

    // MARK: - handleWordSelected — existing entry fast path

    @Test func handleWordSelected_loadsFromExistingEntryWithoutCallingService() async {
        let service = MockTranslating()
        let handler = makeHandler(service: service)
        let ctx = MockVocabContext()
        ctx.existing = VocabularyEntry(
            word: "delta",
            translation: "預存翻譯",
            context: "",
            explanation: nil,
            partOfSpeech: nil,
            bookTitle: "B",
            chapterTitle: "C"
        )

        handler.handleWordSelected(word: "delta", context: "some ctx", vocabularyContext: ctx)
        // No task is spawned on the fast path; drain is a no-op.
        await drain(handler)

        #expect(service.quickCalls == 0, "existing entry must short-circuit before hitting the translation service")
        #expect(handler.translationResult?.translation == "預存翻譯")
        #expect(handler.isSaved == true)
        #expect(handler.isTranslating == false)
    }

    // MARK: - handleWordSelected — guest path

    @Test func handleWordSelected_guestPath_savesViaContextWhenNotLoggedIn() async {
        let service = MockTranslating()
        let handler = makeHandler(loggedIn: false, service: service)
        let ctx = MockVocabContext()

        handler.handleWordSelected(word: "epsilon", context: "ctx", vocabularyContext: ctx)
        await drain(handler)

        #expect(service.quickCalls == 0, "guest tap must NOT hit the translation service")
        #expect(ctx.savedSelections.count == 1)
        #expect(ctx.savedTranslations.first == "")
        #expect(handler.isSaved == true)
    }

    // MARK: - handleWordSelected — fresh translate + autoSave

    @Test func handleWordSelected_freshTranslate_autoSavesOnSuccess() async {
        let service = MockTranslating()
        service.quickResult = .success(TranslationResult(translation: "rendered", partOfSpeech: nil, explanation: nil))
        let handler = makeHandler(service: service)
        let ctx = MockVocabContext()

        handler.handleWordSelected(word: "zeta", context: "ctx", vocabularyContext: ctx)
        await drain(handler)

        #expect(service.quickCalls == 1)
        #expect(handler.translationResult?.translation == "rendered")
        #expect(handler.isTranslating == false)
        #expect(handler.translationErrorMessage == nil)
        #expect(ctx.savedTranslations.first == "rendered", "fresh translate path must auto-save through the protocol")
    }

    // MARK: - handleWordSelected — failure path

    @Test func handleWordSelected_setsErrorMessageOnTranslationFailure() async {
        let service = MockTranslating()
        service.quickResult = .failure(MockError.canned("boom"))
        let handler = makeHandler(service: service)
        let ctx = MockVocabContext()

        handler.handleWordSelected(word: "eta", context: "ctx", vocabularyContext: ctx)
        await drain(handler)

        #expect(handler.translationResult == nil)
        #expect(handler.isTranslating == false)
        #expect(handler.translationErrorMessage != nil)
        #expect(handler.translationErrorMessage?.contains("boom") == true,
                "failure message must surface the underlying error description")
        #expect(ctx.savedSelections.isEmpty, "failed translate must NOT auto-save anything")
    }

    // MARK: - deleteFromVocabulary

    @Test func deleteFromVocabulary_callsContextDeleteAndDismisses() {
        let handler = makeHandler()
        let ctx = MockVocabContext()
        // Pre-populate selection so we can verify dismiss() clears it.
        handler.wordSelection = WordSelection(word: "theta", context: "ctx", position: .zero)
        handler.isSaved = true

        handler.deleteFromVocabulary("theta", context: ctx)

        #expect(ctx.deletedWords == ["theta"])
        #expect(handler.wordSelection == nil, "delete must trigger dismiss()")
        #expect(handler.isSaved == false)
    }
}
#endif
