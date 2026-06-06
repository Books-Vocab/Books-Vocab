//
//  ActiveNotebookStore.swift
//  BooksBrowser
//

import Foundation

/// 全域 active notebook 游標的單一存取點。
///
/// 「active notebook」= 決定新選詞預設歸進哪一本的全域指標（per-book
/// `Book.preferredNotebookId` 走 CloudKit，不在此）。先前散落在多處直接讀寫
/// UserDefaults key `activeNotebookId`：NotebookListView 的 @AppStorage、
/// `Book.resolvedNotebookId`、`NotebookListCoordinator` 的 stale 清理、登出 / 帳號切換
/// 的 removeObject…。本 store 收斂**寫入**入口，為後續三層後端化（iCloud KVS + backend
/// LWW，對齊 `ReviewSettingsStore`）鋪路 —— 屆時 `updatedAt` 推進與 cloud 寫只需加在
/// 這三個 method，不必在每個呼叫點重複（否則直寫 UserDefaults 會繞過 LWW 時戳）。
///
/// 此階段（B2a）為 behavior-preserving：仍只讀寫同一 UserDefaults key，語意與舊碼等價
/// （`clearStale` / `clear` 皆 removeObject → 讀取 fall through 到 `default`）。刻意做成
/// 無 @Observable / 無 in-memory 快取的 thread-safe wrapper：清除點在背景 service thread
/// （AuthManager / KGService+Sync / LocalDataCleaner），UserDefaults 本身 thread-safe，
/// 不引入跨 thread 的 @Observable mutation。讀取點（`Book` / `PodcastPlayerView` 為
/// `@Model` 跨 thread）維持直讀同一 key，值與本 store 一致，故不收斂進來。
final class ActiveNotebookStore {
    static let shared = ActiveNotebookStore(defaults: .standard)

    /// 無綁定 notebook 時的系統預設本 id（對齊 `Book.resolvedNotebookId` fallback）。
    static let defaultNotebookId = "default"
    private static let storageKey = "activeNotebookId"

    private let defaults: UserDefaults

    init(defaults: UserDefaults) {
        self.defaults = defaults
    }

    /// 當前全域 active notebook id；未設定時回 `defaultNotebookId`。
    var activeNotebookId: String {
        defaults.string(forKey: Self.storageKey) ?? Self.defaultNotebookId
    }

    /// 使用者切換 active notebook，或刪除後 fallback 指派。
    func setActive(_ id: String) {
        defaults.set(id, forKey: Self.storageKey)
    }

    /// active notebook 指向的本子已不可見（跨裝置刪除 / 孤兒回收）時清除，讓讀取
    /// fall through 到 `default`，避免新詞變孤兒。B2b 將改為寫回 `default` 並推進
    /// `updatedAt` 以跨裝置同步此重置（目前 removeObject 為 behavior-preserving）。
    func clearStale() {
        defaults.removeObject(forKey: Self.storageKey)
    }

    /// 登出 / 帳號切換時清除本機 active notebook 狀態。
    func clear() {
        defaults.removeObject(forKey: Self.storageKey)
    }
}
