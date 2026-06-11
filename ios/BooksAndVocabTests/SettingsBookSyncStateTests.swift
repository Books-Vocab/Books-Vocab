import Testing
@testable import BooksAndVocab

/// Pins the CloudKit 書庫同步狀態 → Settings 列的 presentation 映射
/// （CloudKitMirroringMonitor.Phase → SettingsPresenterState.BookSyncState）。
/// 書庫綁 Apple ID 不綁 app 帳號，列的顯示與登入無關；唯一隱藏條件 =
/// localOnly（此 container 沒接 CloudKit，顯示同步狀態是誤導）。
@Suite("SettingsBookSyncState")
struct SettingsBookSyncStateTests {

    @Test func localOnlyHidesRow() {
        #expect(SettingsPresenterState.BookSyncState.from(phase: .localOnly) == nil)
    }

    @Test func waitingFirstEventShowsCheckingInProgress() {
        let state = SettingsPresenterState.BookSyncState.from(phase: .waitingFirstEvent)
        #expect(state?.text == L10n.string("確認中…"))
        #expect(state?.tone == .progress)
        #expect(state?.detail == nil)
    }

    @Test func restoringShowsRestoringInProgress() {
        let state = SettingsPresenterState.BookSyncState.from(phase: .restoring)
        #expect(state?.text == L10n.string("還原中…"))
        #expect(state?.tone == .progress)
        #expect(state?.detail == nil)
    }

    /// failed 必帶錯誤描述（observability 要求可見，與 monitor phase 契約一致）。
    @Test func failedCarriesErrorDetail() {
        let state = SettingsPresenterState.BookSyncState.from(phase: .failed("CKError 引導測試"))
        #expect(state?.text == L10n.string("同步異常"))
        #expect(state?.tone == .warning)
        #expect(state?.detail == "CKError 引導測試")
    }

    /// 空錯誤訊息 normalize 成 nil（防渲染空 caption 行；monitor 端另有 fallback）。
    @Test func failedWithEmptyMessageDropsDetail() {
        let state = SettingsPresenterState.BookSyncState.from(phase: .failed(""))
        #expect(state?.text == L10n.string("同步異常"))
        #expect(state?.detail == nil)
    }

    @Test func settledShowsSynced() {
        let state = SettingsPresenterState.BookSyncState.from(phase: .settled)
        #expect(state?.text == L10n.string("已同步"))
        #expect(state?.tone == .success)
        #expect(state?.detail == nil)
    }
}
