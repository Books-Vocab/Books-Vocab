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

    /// CAS 的「不回捲」分支：await 期間背景 pull 帶回權威值（值已不等於我們的樂觀寫入），
    /// 此時回捲會用舊值蓋掉新鮮值且不再推送。用 handler 在拋錯前改值即可確定性驅動。
    @Test func setArchived_doesNotRollBackWhenValueChangedDuringFlight() async throws {
        let context = try makeContext()
        let entry = makeEntry(cardId: "root-card", word: "abate")
        entry.notebookId = "nb-1"
        context.insert(entry)

        let spy = SpyKGService()
        spy.archiveCardHandler = { _ in
            // 模擬背景 pull 在 in-flight 期間寫入權威值 false
            entry.isArchived = false
            throw TestFailure.offline
        }
        let state = WordDetailSceneState()

        await state.setArchived(true, for: entry, kgService: spy, modelContext: context)

        #expect(entry.isArchived == false, "值已被他人改動時不可回捲")
        #expect(state.actionError != nil)
    }

    /// CAS 的「要回捲」分支，並補上 commit message 稱為「載重側」的持久化斷言。
    @Test func setArchived_rollbackPersistsWhenValueUntouched() async throws {
        let context = try makeContext()
        let entry = makeEntry(cardId: "root-card", word: "abate")
        entry.notebookId = "nb-1"
        context.insert(entry)

        let spy = SpyKGService()
        spy.archiveCardHandler = { _ in throw TestFailure.offline }
        let state = WordDetailSceneState()

        await state.setArchived(true, for: entry, kgService: spy, modelContext: context)

        #expect(entry.isArchived == false)
        #expect(context.hasChanges == false, "回捲側要把樂觀值從磁碟撤下來")
    }

    /// 跨領域：連結操作留下的錯誤**不可**被一次成功的封存抹掉——連結失敗會靜靜回捲，
    /// 那則訊息是使用者唯一的解釋；封存的成功則自帶圖示回饋。
    @Test func setArchived_successDoesNotClearLinkError() async throws {
        let context = try makeContext()
        let entry = makeEntry(cardId: "root-card", word: "abate")
        entry.notebookId = "nb-1"
        context.insert(entry)

        let spy = SpyKGService()
        let state = WordDetailSceneState()
        state.actionError = "刪除連結失敗"   // 模擬 link writer 留下的訊息（kind = nil，非 .archive）

        await state.setArchived(true, for: entry, kgService: spy, modelContext: context)

        #expect(entry.isArchived)
        #expect(state.actionError == "刪除連結失敗", "封存成功不得吃掉別類動作的錯誤")
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
