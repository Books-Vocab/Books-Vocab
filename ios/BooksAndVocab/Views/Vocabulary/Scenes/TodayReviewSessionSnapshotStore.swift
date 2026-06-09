import Foundation

struct TodayReviewSessionSnapshotStore {
    private static let defaultsKey = "kg.review.activeSession.v1"
    private static let maxAge: TimeInterval = 7 * 24 * 60 * 60

    struct Snapshot: Codable {
        struct QueueItem: Codable {
            let persistenceID: String
            let baseline: ReviewBaseline
        }

        struct SubmittedAnswer: Codable {
            let feedbackRaw: Int
            let answeredAt: Date
            let reviewRecordID: UUID
            /// Whether the DB flush (reviewCount/nextReviewAt/streak update +
            /// ReviewRecord insert) confirmed success for this answer. Restore
            /// re-flushes any answer left `false` so a failed background flush
            /// (DB error / entry missing) can't strand the card's schedule while
            /// the UI shows it as reviewed.
            let flushed: Bool

            init(feedbackRaw: Int, answeredAt: Date, reviewRecordID: UUID, flushed: Bool) {
                self.feedbackRaw = feedbackRaw
                self.answeredAt = answeredAt
                self.reviewRecordID = reviewRecordID
                self.flushed = flushed
            }

            // Backward compat: legacy blobs predate `flushed`. Those answers
            // were already flushed (the bug is a rare flush failure), so a
            // missing key decodes to `true` — never re-flush historical data.
            init(from decoder: Decoder) throws {
                let c = try decoder.container(keyedBy: CodingKeys.self)
                feedbackRaw = try c.decode(Int.self, forKey: .feedbackRaw)
                answeredAt = try c.decode(Date.self, forKey: .answeredAt)
                reviewRecordID = try c.decode(UUID.self, forKey: .reviewRecordID)
                flushed = try c.decodeIfPresent(Bool.self, forKey: .flushed) ?? true
            }
        }

        let userId: String
        let sessionStartTime: Date
        let currentIndex: Int
        let queue: [QueueItem]
        let submissions: [Int: SubmittedAnswer]
        let updatedAt: Date
    }

    struct ReviewBaseline: Codable {
        let reviewIntervalHours: Double
        let nextReviewAt: Date
        let lastReviewedAt: Date?
        let reviewCount: Int
        let lapseCount: Int
        let reviewStreak: Int
        let lastReviewFeedbackRaw: Int
    }

    // MARK: - Public API

    static func load(for userId: String) -> Snapshot? {
        guard let snapshot = readStore()[userId] else { return nil }

        guard Date().timeIntervalSince(snapshot.updatedAt) <= maxAge else {
            clear(for: userId)
            return nil
        }

        return snapshot
    }

    static func save(_ snapshot: Snapshot) {
        var store = readStore()
        store[snapshot.userId] = snapshot
        writeStore(store)
    }

    /// Passing `nil` clears every user's snapshot; passing a `userId` clears only that user's.
    static func clear(for userId: String?) {
        guard let userId else {
            UserDefaults.standard.removeObject(forKey: defaultsKey)
            return
        }

        var store = readStore()
        guard store[userId] != nil else { return }
        store.removeValue(forKey: userId)
        writeStore(store)
    }

    // MARK: - Persistence

    /// Reads the per-user snapshot map. Transparently migrates the legacy
    /// single-`Snapshot` payload (pre per-user keying) into the new dictionary.
    private static func readStore() -> [String: Snapshot] {
        guard let data = UserDefaults.standard.data(forKey: defaultsKey) else { return [:] }

        if let store = try? JSONDecoder().decode([String: Snapshot].self, from: data) {
            return store
        }

        // Migration: legacy payload stored a bare Snapshot keyed by `defaultsKey`.
        if let legacy = try? JSONDecoder().decode(Snapshot.self, from: data) {
            let migrated = [legacy.userId: legacy]
            writeStore(migrated)
            return migrated
        }

        return [:]
    }

    private static func writeStore(_ store: [String: Snapshot]) {
        if store.isEmpty {
            UserDefaults.standard.removeObject(forKey: defaultsKey)
            return
        }
        guard let data = try? JSONEncoder().encode(store) else { return }
        UserDefaults.standard.set(data, forKey: defaultsKey)
    }
}
