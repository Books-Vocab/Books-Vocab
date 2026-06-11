import Foundation
import Testing
@testable import BooksAndVocab

/// Pins the CloudKit mirroring observability contract（2026-06-11 書庫透明化）：
/// 書架空狀態必須能區分「真的沒書」與「雲端還沒拉完/正在還原/同步失敗」。
/// UI 只在 `phase == .settled` 時才允許把 0 本書講成「書庫是空的」。
///
/// 狀態機輸入是自定 `MirroringEventSnapshot`（framework 的
/// `NSPersistentCloudKitContainer.Event` 無 public init，production 端在
/// notification handler 做 Event → snapshot 映射，測試直接餵 snapshot）。
@MainActor
struct CloudKitMirroringMonitorTests {

    private func makeMonitor(cloudKitEnabled: Bool = true) -> CloudKitMirroringMonitor {
        let monitor = CloudKitMirroringMonitor()
        monitor.configure(cloudKitEnabled: cloudKitEnabled)
        return monitor
    }

    private func importEvent(ended: Bool, succeeded: Bool = true, error: String? = nil) -> MirroringEventSnapshot {
        MirroringEventSnapshot(
            type: .import,
            endedAt: ended ? Date() : nil,
            succeeded: succeeded,
            errorDescription: error
        )
    }

    /// CloudKit 容器未啟用（UI-testing ephemeral / fallback / local-only retry）：
    /// 永遠 localOnly，空書架直接走「真空」語意，不得卡在還原中。
    @Test func disabledContainerIsLocalOnly() {
        let monitor = makeMonitor(cloudKitEnabled: false)
        #expect(monitor.phase == .localOnly)
        monitor.apply(importEvent(ended: false))
        #expect(monitor.phase == .localOnly)
    }

    /// 啟用但尚無任何 mirroring 事件：還不知道雲端有沒有資料，
    /// 不得宣稱「真空」。
    @Test func enabledWithNoEventsIsWaitingFirstEvent() {
        let monitor = makeMonitor()
        #expect(monitor.phase == .waitingFirstEvent)
        #expect(!monitor.emptyMeansEmpty)
    }

    /// import 進行中（endedAt nil）→ restoring。
    @Test func inFlightImportIsRestoring() {
        let monitor = makeMonitor()
        monitor.apply(importEvent(ended: false))
        #expect(monitor.phase == .restoring)
        #expect(!monitor.emptyMeansEmpty)
    }

    /// 首次 import 成功收尾 → settled；此後 0 本書才可以講「真空」。
    @Test func completedImportSettles() {
        let monitor = makeMonitor()
        monitor.apply(importEvent(ended: false))
        monitor.apply(importEvent(ended: true))
        #expect(monitor.phase == .settled)
        #expect(monitor.emptyMeansEmpty)
    }

    /// settled 之後的 export / 後續事件不得把狀態退回 restoring 以外
    /// 的不確定態（export 是上行，與「雲端資料還沒下來」無關）。
    @Test func exportAfterSettledStaysSettled() {
        let monitor = makeMonitor()
        monitor.apply(importEvent(ended: true))
        monitor.apply(MirroringEventSnapshot(type: .export, endedAt: nil, succeeded: true, errorDescription: nil))
        #expect(monitor.phase == .settled)
    }

    /// 事件失敗 → failed 並保留錯誤描述（observability：失敗必須可見）。
    @Test func failedEventSurfacesError() {
        let monitor = makeMonitor()
        monitor.apply(importEvent(ended: true, succeeded: false, error: "CKErrorDomain 9"))
        guard case .failed(let message) = monitor.phase else {
            Issue.record("expected .failed, got \(monitor.phase)")
            return
        }
        #expect(message.contains("CKErrorDomain"))
        #expect(!monitor.emptyMeansEmpty)
    }

    /// 失敗後成功的 import 收尾 → 恢復 settled（錯誤不黏死）。
    @Test func successfulImportRecoversFromFailure() {
        let monitor = makeMonitor()
        monitor.apply(importEvent(ended: true, succeeded: false, error: "CKErrorDomain 9"))
        monitor.apply(importEvent(ended: true))
        #expect(monitor.phase == .settled)
    }

    /// setup 成功不等於資料下來了：settled 只認 import 成功收尾。
    @Test func setupSuccessAloneDoesNotSettle() {
        let monitor = makeMonitor()
        monitor.apply(MirroringEventSnapshot(type: .setup, endedAt: Date(), succeeded: true, errorDescription: nil))
        #expect(monitor.phase == .waitingFirstEvent)
        #expect(!monitor.emptyMeansEmpty)
    }
}
