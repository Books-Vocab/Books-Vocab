import Testing
@testable import BooksAndVocab

/// 覆蓋 `VocabularyEntry` 的可見性 / 上傳判準 computed properties。
///
/// 這些 computed property 是 in-memory filter（StatsPresentation、
/// VocabularyListView 等）的真相。@Query 走的是平行的
/// `knowledgeListPredicate(notebookId:)` 工廠（SwiftData #Predicate 無法
/// 直接引用 computed property，故同條件雙軌表述）—— 本測試鎖 computed
/// 軌不漂移。回歸保護：syncStatus × actionType × isArchived 的組合不可
/// 漂移 —— 尤其 `!isArchived` 不可在任一路徑漏判。
@Suite("VocabularyEntry state predicates")
struct VocabularyEntryStateTests {

    /// 建一筆 entry 並覆寫 sync 狀態欄位（init 預設 syncStatus=0/add/未封存）。
    private func entry(status: Int, action: String, archived: Bool = false) -> VocabularyEntry {
        let e = VocabularyEntry(
            word: "w", translation: "翻譯", context: "ctx", bookTitle: "book"
        )
        e.syncStatus = status
        e.actionType = action
        e.isArchived = archived
        return e
    }

    // MARK: - shouldAppearInKnowledgeList = synced && !delete && !archived

    @Test("synced + add + 未封存 → 入知識列表")
    func knowledgeList_syncedAdd() {
        #expect(entry(status: 1, action: "add").shouldAppearInKnowledgeList)
    }

    @Test("synced 但已封存 → 不入知識列表")
    func knowledgeList_excludesArchived() {
        #expect(!entry(status: 1, action: "add", archived: true).shouldAppearInKnowledgeList)
    }

    @Test("synced 但待刪除 → 不入知識列表")
    func knowledgeList_excludesDelete() {
        #expect(!entry(status: 1, action: "delete").shouldAppearInKnowledgeList)
    }

    @Test("未同步(pending) → 不入知識列表")
    func knowledgeList_excludesPending() {
        #expect(!entry(status: 0, action: "add").shouldAppearInKnowledgeList)
    }

    // MARK: - shouldAppearInArchiveList = synced && !delete && archived

    @Test("synced + 已封存 → 入封存列表")
    func archiveList_syncedArchived() {
        #expect(entry(status: 1, action: "add", archived: true).shouldAppearInArchiveList)
    }

    @Test("synced + 未封存 → 不入封存列表（與知識列表互斥）")
    func archiveList_excludesUnarchived() {
        #expect(!entry(status: 1, action: "add").shouldAppearInArchiveList)
    }

    @Test("已封存但待刪除 → 不入封存列表")
    func archiveList_excludesDelete() {
        #expect(!entry(status: 1, action: "delete", archived: true).shouldAppearInArchiveList)
    }

    @Test("知識列表與封存列表恆互斥")
    func knowledgeAndArchiveAreMutuallyExclusive() {
        for archived in [true, false] {
            let e = entry(status: 1, action: "add", archived: archived)
            #expect(e.shouldAppearInKnowledgeList != e.shouldAppearInArchiveList)
        }
    }

    // MARK: - shouldAppearInReader = !delete && !archived && !excludedFromReader

    @Test("未刪除 + 未封存 + 未排除 → 入 Reader（含未同步）")
    func reader_pendingStillShows() {
        #expect(entry(status: 0, action: "add").shouldAppearInReader)
    }

    @Test("已封存 → 不入 Reader")
    func reader_excludesArchived() {
        #expect(!entry(status: 1, action: "add", archived: true).shouldAppearInReader)
    }

    @Test("待刪除 → 不入 Reader")
    func reader_excludesDelete() {
        #expect(!entry(status: 1, action: "delete").shouldAppearInReader)
    }

    // MARK: - shouldUploadOnNextSync = pendingAdd || pendingDelete || failedAdd || failedDelete

    @Test("pending + add → 待上傳")
    func upload_pendingAdd() {
        #expect(entry(status: 0, action: "add").shouldUploadOnNextSync)
    }

    @Test("failed + delete → 待上傳（重試）")
    func upload_failedDelete() {
        #expect(entry(status: 2, action: "delete").shouldUploadOnNextSync)
    }

    @Test("synced + add → 不再上傳")
    func upload_syncedAddSkips() {
        #expect(!entry(status: 1, action: "add").shouldUploadOnNextSync)
    }
}
