import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct WordDetailSceneStateTests {

    @Test func refreshPresentation_buildsPresenterState() {
        let entry = makeEntry(cardId: "root-card", word: "meticulous")
        let peer = makeEntry(cardId: "peer-card", word: "precise")
        entry.insertLink(
            KGCardLinkSummary(
                id: "link-1",
                cardId: "peer-card",
                word: "precise",
                kind: "shares_usage",
                label: "相關",
                confidence: 0.8,
                reason: "seed"
            ),
            kind: "shares_usage"
        )

        let state = WordDetailSceneState()
        state.refreshPresentation(for: entry, in: [entry, peer])

        #expect(state.presenterState?.title == "meticulous")
        #expect(state.presenterState?.navigableLinkCardIDs == ["peer-card"])
    }

    @Test func linkedEntry_resolvesPeerFromAllEntries() {
        let entry = makeEntry(cardId: "root-card", word: "meticulous")
        let peer = makeEntry(cardId: "peer-card", word: "precise")
        let link = KGCardLinkSummary(
            id: "link-1",
            cardId: "peer-card",
            word: "precise",
            kind: "shares_usage",
            label: "相關",
            confidence: 0.8,
            reason: "seed"
        )

        let state = WordDetailSceneState()
        let resolved = state.linkedEntry(for: link, from: entry, in: [entry, peer])

        #expect(resolved === peer)
    }

    @Test func dismissActionError_clearsBannerState() {
        let state = WordDetailSceneState()
        state.actionError = "error"

        state.dismissActionError()

        #expect(state.actionError == nil)
    }

    // MARK: - Archive

    @Test func setArchived_flipsEntryAndCallsServiceWithNotebookScope() async throws {
        let context = try makeContext()
        let entry = makeEntry(cardId: "root-card", word: "abate")
        entry.notebookId = "nb-1"
        context.insert(entry)

        let spy = SpyKGService()
        let state = WordDetailSceneState()

        await state.setArchived(true, for: entry, kgService: spy, modelContext: context)

        #expect(entry.isArchived)
        #expect(spy.archiveCalls == [.init(word: "abate", archived: true, notebookId: "nb-1")])
        #expect(state.actionError == nil)
        #expect(context.hasChanges == false, "成功路徑要把樂觀值落磁碟")
    }

    /// 共用 banner 只寫不清，失敗訊息會活過後續的成功動作：封存失敗 → 再按一次成功 →
    /// 圖示已翻成已封存，banner 卻還掛著「封存失敗」。
    @Test func setArchived_clearsPreviousErrorOnRetrySuccess() async throws {
        let context = try makeContext()
        let entry = makeEntry(cardId: "root-card", word: "abate")
        entry.notebookId = "nb-1"
        context.insert(entry)

        let spy = SpyKGService()
        spy.archiveCardHandler = { _ in throw TestFailure.offline }
        let state = WordDetailSceneState()

        await state.setArchived(true, for: entry, kgService: spy, modelContext: context)
        #expect(state.actionError != nil)

        spy.archiveCardHandler = { _ in }
        await state.setArchived(true, for: entry, kgService: spy, modelContext: context)

        #expect(entry.isArchived)
        #expect(state.actionError == nil, "成功後必須清掉上一次的失敗訊息")
    }

    /// `guard previous != archived` 是一句行為宣告，沒有測試釘住就只是註解。
    @Test func setArchived_noopsWhenAlreadyInTargetState() async throws {
        let context = try makeContext()
        let entry = makeEntry(cardId: "root-card", word: "abate")
        entry.notebookId = "nb-1"
        entry.isArchived = true
        context.insert(entry)

        let spy = SpyKGService()
        let state = WordDetailSceneState()

        await state.setArchived(true, for: entry, kgService: spy, modelContext: context)

        #expect(spy.archiveCalls.isEmpty, "已在目標狀態不該打伺服器")
        #expect(entry.isArchived)
    }

    @Test func setArchived_false_unarchivesTheEntry() async throws {
        let context = try makeContext()
        let entry = makeEntry(cardId: "root-card", word: "abate")
        entry.notebookId = "nb-1"
        entry.isArchived = true
        context.insert(entry)

        let spy = SpyKGService()
        let state = WordDetailSceneState()

        await state.setArchived(false, for: entry, kgService: spy, modelContext: context)

        #expect(entry.isArchived == false)
        #expect(spy.archiveCalls == [.init(word: "abate", archived: false, notebookId: "nb-1")])
    }

    /// 封存需連線。伺服器拒絕時，樂觀翻轉必須完整回捲——否則本機顯示「已封存」
    /// 但伺服器上沒有，下次 pull 會把它翻回來，使用者看到卡片自己復活。
    @Test func setArchived_rollsBackAndReportsWhenServiceFails() async throws {
        let context = try makeContext()
        let entry = makeEntry(cardId: "root-card", word: "abate")
        entry.notebookId = "nb-1"
        context.insert(entry)

        let spy = SpyKGService()
        spy.archiveCardHandler = { _ in throw TestFailure.offline }
        let state = WordDetailSceneState()

        await state.setArchived(true, for: entry, kgService: spy, modelContext: context)

        // archiveCalls 的斷言不可省：少了它，這個測試對一個「從不做樂觀翻轉、也從不呼叫
        // 伺服器，只負責寫 actionError」的實作同樣會綠——因為期望的終態剛好等於初始態。
        #expect(spy.archiveCalls == [.init(word: "abate", archived: true, notebookId: "nb-1")])
        #expect(entry.isArchived == false)
        #expect(state.actionError != nil)
    }

    @Test func setArchived_rollsBackToArchivedWhenUnarchiveFails() async throws {
        let context = try makeContext()
        let entry = makeEntry(cardId: "root-card", word: "abate")
        entry.notebookId = "nb-1"
        entry.isArchived = true
        context.insert(entry)

        let spy = SpyKGService()
        spy.archiveCardHandler = { _ in throw TestFailure.offline }
        let state = WordDetailSceneState()

        await state.setArchived(false, for: entry, kgService: spy, modelContext: context)

        #expect(spy.archiveCalls == [.init(word: "abate", archived: false, notebookId: "nb-1")])
        #expect(entry.isArchived)
        #expect(state.actionError != nil)
    }

    // MARK: - Helpers

    private enum TestFailure: Error {
        case offline
    }

    private func makeContext() throws -> ModelContext {
        let schema = Schema([
            Book.self,
            VocabularyEntry.self,
            ReviewRecord.self,
            Notebook.self,
            PodcastSeries.self,
            PodcastEpisode.self,
            PodcastProgress.self
        ])
        let config = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(for: schema, configurations: [config])
        return ModelContext(container)
    }

    private func makeEntry(cardId: String, word: String) -> VocabularyEntry {
        let entry = VocabularyEntry(
            word: word,
            translation: "\(word)-translation",
            context: "\(word) context",
            bookTitle: "Book"
        )
        entry.kgCardId = cardId
        return entry
    }
}
