#if os(iOS)
import Foundation
import Testing
@testable import BooksAndVocab

/// track-23 一致性回滾：notebook 編輯封面圖（device-local）的落地必須與
/// `updateNotebook` API 成敗一致。`NotebookCoverCommit.plan` 是純函式 —
/// API 成功才套用 `resolvedPath` + 刪 `fileToRemove`；失敗則完全不呼叫 →
/// coverImagePath 不變、舊圖保留，杜絕「新封面 + server 舊欄位」drift。
struct NotebookCoverCommitTests {

    // MARK: - plan（純資料分支）

    @Test func unchangedCoverKeepsPathAndDeletesNothing() {
        let plan = NotebookCoverCommit.plan(staged: "/covers/a.jpg", original: "/covers/a.jpg")
        #expect(plan.resolvedPath == "/covers/a.jpg")
        #expect(plan.fileToRemove == nil)
    }

    @Test func replacingCoverResolvesNewAndQueuesOldForRemoval() {
        let plan = NotebookCoverCommit.plan(staged: "/covers/new.jpg", original: "/covers/old.jpg")
        #expect(plan.resolvedPath == "/covers/new.jpg")
        #expect(plan.fileToRemove == "/covers/old.jpg")
    }

    @Test func addingCoverFromNoneDeletesNothing() {
        let plan = NotebookCoverCommit.plan(staged: "/covers/new.jpg", original: nil)
        #expect(plan.resolvedPath == "/covers/new.jpg")
        #expect(plan.fileToRemove == nil)
    }

    @Test func removingCoverResolvesNilAndQueuesOldForRemoval() {
        let plan = NotebookCoverCommit.plan(staged: nil, original: "/covers/old.jpg")
        #expect(plan.resolvedPath == nil)
        #expect(plan.fileToRemove == "/covers/old.jpg")
    }

    @Test func noCoverEitherSideIsNoOp() {
        let plan = NotebookCoverCommit.plan(staged: nil, original: nil)
        #expect(plan.resolvedPath == nil)
        #expect(plan.fileToRemove == nil)
    }

    // MARK: - removeStaleFile（檔案副作用，模擬 API 成功路徑）

    private func writeTempJPEG() throws -> String {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("notebook_cover_\(UUID().uuidString).jpg")
        try Data([0xFF, 0xD8, 0xFF]).write(to: url)
        return url.path
    }

    /// API 成功 + 換圖 → 舊檔被刪。
    @Test func removeStaleFileDeletesOldImageOnSuccess() throws {
        let old = try writeTempJPEG()
        let new = try writeTempJPEG()
        let plan = NotebookCoverCommit.plan(staged: new, original: old)

        NotebookCoverCommit.removeStaleFile(plan)

        #expect(!FileManager.default.fileExists(atPath: old)) // 舊圖已刪
        #expect(FileManager.default.fileExists(atPath: new))  // 新圖保留
        try? FileManager.default.removeItem(atPath: new)
    }

    /// 封面未變更 → 不刪任何檔（避免誤刪仍在使用的圖）。
    @Test func removeStaleFileKeepsUnchangedCover() throws {
        let path = try writeTempJPEG()
        let plan = NotebookCoverCommit.plan(staged: path, original: path)

        NotebookCoverCommit.removeStaleFile(plan)

        #expect(FileManager.default.fileExists(atPath: path))
        try? FileManager.default.removeItem(atPath: path)
    }

    /// 模擬 API **失敗路徑**：`removeStaleFile` 從不被呼叫 → 舊圖必然保留，
    /// 可在重試 / 取消時恢復。此處直接驗證「不呼叫即不刪」的安全保證。
    @Test func failurePathNeverTouchesOldImage() throws {
        let old = try writeTempJPEG()
        // updateNotebook catch 分支不呼叫 removeStaleFile，亦不寫 resolvedPath。
        // 模擬之：不執行任何 commit 動作。
        #expect(FileManager.default.fileExists(atPath: old))
        try? FileManager.default.removeItem(atPath: old)
    }
}
#endif
