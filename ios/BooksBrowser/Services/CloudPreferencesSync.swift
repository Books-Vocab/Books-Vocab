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

    func set(_ value: String, forKey key: String) {
        kvs.set(value, forKey: key)
    }

    func set(_ value: Double, forKey key: String) {
        kvs.set(value, forKey: key)
    }

    // MARK: - Sync

    func synchronize() {
        kvs.synchronize()
    }
}
