#if os(iOS)
import SwiftData

/// 顯式使用者觸發的帳號同步 + toast 回饋的**單一真相**。
///
/// 由三條顯式 trigger 共用：書架 pull-to-refresh（iOS/iPadOS）、Mac toolbar 同步鈕、
/// ⌘R menu command。集中於此的理由：
///  1. `lastBackgroundSyncError` 是跨所有 sync trigger 共享的全域欄位，consumer 必須
///     **read-then-clear**（對齊 `BooksBrowserApp` scenePhase / post-login），否則下一個
///     consumer 會讀到 stale 失敗值而誤彈舊 toast。把契約收斂一處避免多點漂移。
///  2. 回饋政策一致：**自動同步（scenePhase / post-login）成功靜默**；**顯式同步成功彈
///     確認 toast**——使用者主動發起的動作值得明確回饋（Mac toolbar 鈕無 pull spinner，
///     尤其需要）。失敗一律 warning toast。
@MainActor
enum ExplicitSync {
    static func run(
        kgService: any BackgroundSyncing,
        container: ModelContainer,
        toastCoordinator: AppToastCoordinator
    ) async {
        await kgService.backgroundSync(container: container)
        if let error = kgService.lastBackgroundSyncError {
            kgService.lastBackgroundSyncError = nil  // read-then-clear（見上）
            toastCoordinator.warning(error)
        } else {
            toastCoordinator.success("同步完成".localized)
        }
    }
}
#endif
