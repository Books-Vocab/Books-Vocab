import Foundation

/// iCloud Key-Value Store 同步管理器
/// 負責封裝 NSUbiquitousKeyValueStore 讀寫，並監聽外部變更通知。
final class CloudPreferencesSync {
    static let shared = CloudPreferencesSync()

    private let kvs = NSUbiquitousKeyValueStore.default

    private init() {}

    // MARK: - Read

    func string(forKey key: String) -> String? {
        kvs.string(forKey: key)
    }

    func double(forKey key: String) -> Double? {
        let value = kvs.double(forKey: key)
        guard kvs.object(forKey: key) != nil else { return nil }
        return value
    }

    // MARK: - Write

    /// 寫入後立即 `synchronize()`，避免 set() 緩衝在記憶體靠 ~30-60s auto-flush，
    /// force-quit 在 flush 前導致 iCloud 寫入丟失。設定變更為低頻使用者操作，
    /// 可接受 KVS synchronize 的節流成本。
    func set(_ value: String, forKey key: String) {
        kvs.set(value, forKey: key)
        kvs.synchronize()
    }

    func set(_ value: Double, forKey key: String) {
        kvs.set(value, forKey: key)
        kvs.synchronize()
    }

    // MARK: - Sync

    func synchronize() {
        kvs.synchronize()
    }
}
