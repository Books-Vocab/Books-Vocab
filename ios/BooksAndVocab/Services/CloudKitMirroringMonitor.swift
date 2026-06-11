//
//  CloudKitMirroringMonitor.swift
//  Books & Vocab
//
//  CloudKit mirroring 觀測點（2026-06-11 書庫透明化）。
//
//  問題：書架把「本地 0 列」直接當「沒有書」，對 NSPersistentCloudKitContainer
//  的 purge / import 一無所知 —— 雲端還沒拉完、正在還原、同步失敗，全都長得
//  跟真空一樣。本 monitor 訂閱 mirroring 事件，讓 UI 只在「首次 import 成功
//  收尾」後才允許把 0 本書講成「書庫是空的」。
//
//  framework 的 `NSPersistentCloudKitContainer.Event` 無 public init，
//  notification handler 先映射成自定 `MirroringEventSnapshot` 再餵狀態機，
//  測試（CloudKitMirroringMonitorTests）直接構造 snapshot。
//

import CoreData
import Foundation

struct MirroringEventSnapshot {
    enum EventType {
        case setup
        case `import`
        case export
    }

    let type: EventType
    let endedAt: Date?
    let succeeded: Bool
    let errorDescription: String?
}

@MainActor
@Observable
final class CloudKitMirroringMonitor {
    static let shared = CloudKitMirroringMonitor()

    enum Phase: Equatable {
        /// 此 container 沒接 CloudKit（UI-testing ephemeral / fallback /
        /// local-only retry）：空書架直接走真空語意。
        case localOnly
        /// CloudKit 啟用但尚無任何 mirroring 事件 —— 雲端有沒有資料未知。
        case waitingFirstEvent
        /// import 進行中（還原 / 初次同步）。
        case restoring
        /// 最近一次收尾的事件失敗（帶錯誤描述，observability 要求可見）。
        case failed(String)
        /// 首次 import 成功收尾後恆 settled —— 0 本書才可以講「真空」。
        case settled
    }

    // @ObservationIgnored 不變式：configure() 只能在 view tree 掛載前呼叫
    // （AppBootstrap.run / AppStartupRecovery 換 container 重掛整棵樹），
    // 掛載後改值不會觸發重繪。若未來出現「執行期切換 CloudKit」需求，
    // 先拿掉 ignored 再說。
    @ObservationIgnored
    private var cloudKitEnabled = false
    private var hasImportSucceeded = false
    private var importInFlight = false
    private var lastErrorDescription: String?

    @ObservationIgnored
    private var observer: (any NSObjectProtocol)?

    var phase: Phase {
        guard cloudKitEnabled else { return .localOnly }
        if hasImportSucceeded { return .settled }
        if let error = lastErrorDescription { return .failed(error) }
        if importInFlight { return .restoring }
        return .waitingFirstEvent
    }

    /// UI 是否可以把「本地 0 列」解讀成「使用者真的沒有資料」。
    var emptyMeansEmpty: Bool {
        switch phase {
        case .settled, .localOnly: return true
        case .waitingFirstEvent, .restoring, .failed: return false
        }
    }

    /// AppBootstrap 在 container 建立後呼叫：宣告本次啟動的 store 是否接
    /// CloudKit。未接（ephemeral / fallback / local-only retry）時事件永遠
    /// 不會來，不得讓 UI 卡在「還原中」。
    func configure(cloudKitEnabled: Bool) {
        self.cloudKitEnabled = cloudKitEnabled
    }

    /// 訂閱 mirroring 事件（object: nil —— SwiftData 內部持有 container，
    /// app 層拿不到實例，但 notification 是全程序廣播）。冪等。
    func start() {
        guard observer == nil else { return }
        observer = NotificationCenter.default.addObserver(
            forName: NSPersistentCloudKitContainer.eventChangedNotification,
            object: nil,
            queue: nil
        ) { note in
            guard let event = note.userInfo?[NSPersistentCloudKitContainer.eventNotificationUserInfoKey]
                    as? NSPersistentCloudKitContainer.Event else { return }
            let snapshot = MirroringEventSnapshot(
                type: Self.mapType(event.type),
                endedAt: event.endDate,
                succeeded: event.succeeded,
                errorDescription: event.error?.localizedDescription
            )
            Task { @MainActor in
                CloudKitMirroringMonitor.shared.apply(snapshot)
            }
        }
    }

    /// 狀態機輸入（internal 供測試直餵）。
    func apply(_ snapshot: MirroringEventSnapshot) {
        guard cloudKitEnabled else { return }

        // 取證線：mirroring 活動全量留痕（書庫絞殺案的觀測缺口）。
        AppLog.app.info("cloudkit.mirroring type=\(String(describing: snapshot.type), privacy: .public) ended=\(snapshot.endedAt != nil) ok=\(snapshot.succeeded) err=\(snapshot.errorDescription ?? "-", privacy: .public)")

        switch snapshot.type {
        case .import:
            if snapshot.endedAt == nil {
                importInFlight = true
            } else {
                importInFlight = false
                if snapshot.succeeded {
                    hasImportSucceeded = true
                    lastErrorDescription = nil
                } else {
                    lastErrorDescription = snapshot.errorDescription ?? "unknown CloudKit import error"
                }
            }
        case .setup, .export:
            // setup 成功 ≠ 資料下來了（settled 只認 import 成功收尾）；
            // 失敗仍要可見。
            if snapshot.endedAt != nil, !snapshot.succeeded {
                lastErrorDescription = snapshot.errorDescription ?? "unknown CloudKit sync error"
            }
        }
    }

    private static func mapType(_ type: NSPersistentCloudKitContainer.EventType) -> MirroringEventSnapshot.EventType {
        switch type {
        case .setup: return .setup
        case .import: return .import
        case .export: return .export
        @unknown default: return .setup
        }
    }
}
