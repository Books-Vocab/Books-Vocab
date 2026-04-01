import Foundation

enum AppObservationLevel: String {
    case debug = "DEBUG"
    case info = "INFO"
    case warning = "WARN"
    case error = "ERROR"
}

struct AppObservationEntry: Sendable {
    let timestamp: Date
    let level: AppObservationLevel
    let category: String
    let message: String

    var previewLine: String {
        let time = AppDateFormatters.hhmmss.string(from: timestamp)
        return "\(time) [\(level.rawValue)] \(message)"
    }
}

struct AppObservationPreview: Sendable {
    let entries: [AppObservationEntry]
    let totalCount: Int
}

final class AppObservationStore: @unchecked Sendable {
    static let shared = AppObservationStore()

    private let lock = NSLock()
    private let maxEntries = 200
    private var entries: [AppObservationEntry] = []

    private init() {}

    func record(level: AppObservationLevel, category: String, message: String) {
        lock.lock()
        defer { lock.unlock() }

        entries.append(
            AppObservationEntry(
                timestamp: Date(),
                level: level,
                category: category,
                message: message
            )
        )

        if entries.count > maxEntries {
            entries.removeFirst(entries.count - maxEntries)
        }
    }

    func preview(limit: Int = 8) -> AppObservationPreview {
        lock.lock()
        defer { lock.unlock() }
        return AppObservationPreview(entries: Array(entries.suffix(limit)), totalCount: entries.count)
    }

    func clear() {
        lock.lock()
        defer { lock.unlock() }
        entries.removeAll(keepingCapacity: false)
    }
}
