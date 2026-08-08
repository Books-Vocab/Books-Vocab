import Foundation

/// 延後執行的 TipKit datastore reset。
///
/// TipKit 規定 `Tips.resetDatastore()` 必須在 `Tips.configure()` **之前**呼叫，
/// 之後呼叫一律 throw。所以語言切換不能就地 reset（那時 TipKit 早已 configure）：
/// 改成只記一個旗標，由下次啟動的 TipKit 初始化路徑在 configure 之前消費。
///
/// 旗標**只在 reset 真的成功時才清掉**。語言切換會經由
/// `.id(appLanguage.selection)` 重建整棵 view tree，啟動用的 `.task` 因此會在同一個
/// process 內再跑一次；那一次 reset 必然 throw（已 configure），旗標必須留著，
/// 等下一次冷啟動兌現。無條件清旗標＝ reset 永遠不會發生＝ TipKit 文案卡在舊語言。
///
/// 背景：APP-20260806-498c25（就地 reset 在 Debug trap、在 Release 靜默失敗）。
enum PendingTipsReset {
    static let defaultsKey = "kg_pending_tips_reset"

    static func mark(in defaults: UserDefaults = .standard) {
        defaults.set(true, forKey: defaultsKey)
    }

    static func isPending(in defaults: UserDefaults = .standard) -> Bool {
        defaults.bool(forKey: defaultsKey)
    }

    static func clear(in defaults: UserDefaults = .standard) {
        defaults.removeObject(forKey: defaultsKey)
    }

    /// 有待辦時執行 `reset`，成功才清旗標；失敗保留旗標留待下次冷啟動重試。
    static func consume(in defaults: UserDefaults = .standard, reset: () throws -> Void) {
        guard isPending(in: defaults) else { return }
        do {
            try reset()
            clear(in: defaults)
        } catch {
            AppLog.app.error(
                "Deferred Tips.resetDatastore failed, retrying next launch: \(error.localizedDescription)"
            )
        }
    }
}
