import Foundation
import SwiftData

struct TodayReviewSessionPersistenceController {
    private(set) var queuePersistenceIDs: [String]
    private(set) var queueBaselines: [TodayReviewSessionSnapshotStore.ReviewBaseline]
    private let currentUserID: String?

    init(queue: [VocabularyEntry], currentUserID: String?) {
        self.queuePersistenceIDs = queue.map(ReviewSessionPersistence.persistenceID(for:))
        self.queueBaselines = queue.map(ReviewSessionPersistence.makeBaseline(from:))
        self.currentUserID = currentUserID
    }

    init(
        queuePersistenceIDs: [String],
        queueBaselines: [TodayReviewSessionSnapshotStore.ReviewBaseline],
        currentUserID: String?
    ) {
        self.queuePersistenceIDs = queuePersistenceIDs
        self.queueBaselines = queueBaselines
        self.currentUserID = currentUserID
    }

    mutating func syncQueueMetadata(for queue: [VocabularyEntry]) {
        queuePersistenceIDs = queue.map(ReviewSessionPersistence.persistenceID(for:))
        queueBaselines = queue.map(ReviewSessionPersistence.makeBaseline(from:))
    }

    func flushPendingAnswers(
        submittedAnswers: [Int: TodayReviewState.SubmittedAnswer],
        container: ModelContainer,
        reviewSettings: ReviewSettings,
        onFinalize: @escaping @MainActor () -> Void = {},
        onFailure: (@MainActor @Sendable () -> Void)? = nil,
        onFlushed: @escaping @MainActor ([Int]) -> Void
    ) {
        ReviewSessionPersistence.flushPendingAnswers(
            queuePersistenceIDs: queuePersistenceIDs,
            queueBaselines: queueBaselines,
            submittedAnswers: submittedAnswers,
            container: container,
            reviewSettings: reviewSettings,
            onFlushed: { indices in
                onFlushed(indices)
                onFinalize()
            },
            onFailure: onFailure
        )
    }

    func persistSnapshot(
        sessionStartTime: Date,
        currentIndex: Int,
        queueCount: Int,
        submittedAnswers: [Int: TodayReviewState.SubmittedAnswer]
    ) {
        guard let currentUserID else { return }
        ReviewSessionPersistence.persistSnapshot(
            userId: currentUserID,
            sessionStartTime: sessionStartTime,
            currentIndex: currentIndex,
            queueCount: queueCount,
            queuePersistenceIDs: queuePersistenceIDs,
            queueBaselines: queueBaselines,
            submittedAnswers: submittedAnswers
        )
    }

    func clearSnapshot() {
        ReviewSessionPersistence.clearSnapshot(for: currentUserID)
    }
}
