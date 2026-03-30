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

    static func load(for userId: String) -> Snapshot? {
        guard let data = UserDefaults.standard.data(forKey: defaultsKey),
              let snapshot = try? JSONDecoder().decode(Snapshot.self, from: data),
              snapshot.userId == userId else {
            return nil
        }

        guard Date().timeIntervalSince(snapshot.updatedAt) <= maxAge else {
            clear(for: userId)
            return nil
        }

        return snapshot
    }

    static func save(_ snapshot: Snapshot) {
        guard let data = try? JSONEncoder().encode(snapshot) else { return }
        UserDefaults.standard.set(data, forKey: defaultsKey)
    }

    static func clear(for userId: String?) {
        guard let userId else {
            UserDefaults.standard.removeObject(forKey: defaultsKey)
            return
        }

        guard let data = UserDefaults.standard.data(forKey: defaultsKey),
              let snapshot = try? JSONDecoder().decode(Snapshot.self, from: data),
              snapshot.userId == userId else {
            return
        }

        UserDefaults.standard.removeObject(forKey: defaultsKey)
    }
}
