#if os(iOS)
import SwiftData

/// 顯式使用者觸發的帳號同步 + 資格 gate + toast 回饋的**單一真相**。
///
/// 由三條顯式 trigger 共用：書架 pull-to-refresh（iOS/iPadOS）、Mac toolbar 同步鈕、
/// ⌘R menu command。集中於此的理由：
///  1. **資格 gate**：未登入 / demo 模式時靜默 no-op，對齊 `BooksAndVocabApp`
///     scenePhase / post-login 的 `guard isLoggedIn, !isDemoMode`。否則空書架（正是
///     登出用戶會看到的畫面）下拉刷新會讓 `backgroundSync` 跑到 `currentAuthToken()`
///     拋 `unauthorized` → `handleUnauthorized` + 誤彈「登入已過期」。集中於此保證**本路徑
///     的三條 trigger**（pull-to-refresh / toolbar / ⌘R）一致，含修掉 ⌘R 既有的未 gate
///     缺口。eligibility 以 bool 傳入而非整個 `AuthManaging`（interface segregation，亦免
///     去重量 mock）。註：Settings「立即同步」為第四條觸發、**不**經本路徑，於
///     `SettingsCoordinator.resync` 自身 site 以同政策 gate。
///  2. `lastBackgroundSyncError` 是跨所有 sync trigger 共享的全域欄位，consumer 必須
///     **read-then-clear**（對齊 scenePhase / post-login），否則下一個 consumer 會讀到
///     stale 失敗值而誤彈舊 toast。把契約收斂一處避免多點漂移。
///  3. 回饋政策一致：**自動同步（scenePhase / post-login）成功靜默**；**顯式同步成功彈
///     確認 toast**——使用者主動發起的動作值得明確回饋（Mac toolbar 鈕無 pull spinner，
///     尤其需要）。失敗一律 warning toast。
@MainActor
enum ExplicitSync {
    static func run(
        kgService: any BackgroundSyncing,
        isLoggedIn: Bool,
        isDemoMode: Bool,
        container: ModelContainer,
        toastCoordinator: AppToastCoordinator
    ) async {
        // 資格 gate：只有真帳號才同步。登出 / demo 一律靜默 no-op（login CTA 就在空書架上，
        // 不需 toast 打斷下拉手勢）。對齊自動同步 trigger 的 guard。
        guard isLoggedIn, !isDemoMode else { return }

        await kgService.backgroundSync(container: container)

        // 使用者中途離開（下拉刷新的 task 被取消）：那一輪並未跑完，既不該報成功也
        // 不該報失敗——直接閉嘴。少了這道檢查，被取消的同步會因為
        // `lastBackgroundSyncError == nil` 而彈出綠色「同步完成」，替一輪根本沒推也
        // 沒拉的同步背書。`backgroundSync` 對應地也不推進 `lastSyncDate`。
        if Task.isCancelled {
            AppLog.kg.info("ExplicitSync cancelled — suppressing outcome toast")
            return
        }

        if let error = kgService.lastBackgroundSyncError {
            kgService.lastBackgroundSyncError = nil  // read-then-clear（見上）
            toastCoordinator.warning(error)
        } else {
            toastCoordinator.success("同步完成".localized)
        }
    }
}
#endif
