import Foundation
import Observation
import SwiftUI

/// Per-user 自動連結（backend judge pipeline）開關的本地快取。執行語意的權威在
/// 後端 user config 的 `auto_link` group（pipeline 讀它決定是否跑 judge）；本地
/// 只負責 UI 顯示與離線快取。與 translation / review_* 家族不同：無 iCloud KV 層，
/// 跨裝置一致性靠後端 `updated_at` 真 LWW（新 group 無 cold-start-only 歷史包袱，
/// server 較新即套用）。
@Observable
final class AutoLinkSettingsStore {
    static let shared = AutoLinkSettingsStore()

    private enum Keys {
        static let enabled = "auto_link_enabled"
        static let updatedAt = "auto_link_updated_at"
    }

    private let defaults: UserDefaults
    private(set) var isEnabled: Bool
    /// 本地最後寫入時戳（epoch 秒）。nil = 本機從未寫過（server 值可無條件套用）。
    private(set) var updatedAt: Double?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        // 預設開啟，對齊後端缺省語意（config 無 auto_link group 視同開啟）。
        self.isEnabled = defaults.object(forKey: Keys.enabled) as? Bool ?? true
        self.updatedAt = defaults.object(forKey: Keys.updatedAt) as? Double
    }

    func setEnabled(_ value: Bool, updatedAt: Double = Date().timeIntervalSince1970) {
        isEnabled = value
        persist(enabled: value, updatedAt: updatedAt)
    }

    /// Server 值套用（真 LWW）：本機從未寫過、或 server 時戳較新才套。
    /// server `updated_at == nil`（從未有 client 寫過）不能蓋掉本地已寫的值。
    func applyServer(enabled: Bool, updatedAt serverUpdatedAt: Double?) {
        if let local = updatedAt {
            guard let serverTs = serverUpdatedAt, serverTs > local else { return }
        }
        isEnabled = enabled
        persist(enabled: enabled, updatedAt: serverUpdatedAt)
    }

    /// Rollback 用：還原值「與原時戳」。時戳必須一起還原，否則 LWW 會把
    /// rollback 誤判成比其他裝置的並發寫入更新。
    func restore(enabled: Bool, updatedAt: Double?) {
        isEnabled = enabled
        persist(enabled: enabled, updatedAt: updatedAt)
    }

    private func persist(enabled: Bool, updatedAt: Double?) {
        self.updatedAt = updatedAt
        defaults.set(enabled, forKey: Keys.enabled)
        if let updatedAt {
            defaults.set(updatedAt, forKey: Keys.updatedAt)
        } else {
            defaults.removeObject(forKey: Keys.updatedAt)
        }
    }
}

// MARK: - Environment

private struct AutoLinkSettingsStoreKey: EnvironmentKey {
    static let defaultValue: AutoLinkSettingsStore = .shared
}

extension EnvironmentValues {
    var autoLinkSettingsStore: AutoLinkSettingsStore {
        get { self[AutoLinkSettingsStoreKey.self] }
        set { self[AutoLinkSettingsStoreKey.self] = newValue }
    }
}
