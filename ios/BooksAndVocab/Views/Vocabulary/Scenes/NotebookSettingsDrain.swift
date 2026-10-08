import Foundation
import SwiftData

/// Re-sends notebook settings that never reached the server.
///
/// A projection stays `.pending`/`.failed` until the server reports it has
/// caught up (see `NotebookSettingsProjection.applyRemote`). Nothing else
/// retries a failed PATCH once the settings screen is gone, so the notebook
/// reconcile path calls this after merging the remote snapshot.
@MainActor
enum NotebookSettingsDrain {
    /// PATCHes every dirty projection with its local per-group values and
    /// timestamps. The server resolves each group last-writer-wins, so sending
    /// a group it already holds is a no-op. Success folds the response back via
    /// `applyRemote`; failure leaves the projection `.failed` with the error.
    static func drain(modelContext: ModelContext, service: any NotebookServing) async {
        let synced = NotebookSettingsSyncState.synced.rawValue
        let descriptor = FetchDescriptor<NotebookSettingsProjection>(
            predicate: #Predicate { $0.syncStateRaw != synced }
        )
        guard let dirty = try? modelContext.fetch(descriptor), !dirty.isEmpty else { return }

        for projection in dirty {
            let policyGroup = projection.reviewPolicyUpdatedAt.map {
                KGNotebookSettingsPatchGroup(
                    value: projection.reviewPolicyOverride.map(KGNotebookReviewPolicy.init),
                    updatedAt: $0
                )
            }
            let layoutGroup = projection.cardLayoutUpdatedAt.map {
                KGNotebookSettingsPatchGroup(
                    value: projection.cardLayoutOverride.map(KGNotebookCardLayout.init),
                    updatedAt: $0
                )
            }
            guard policyGroup != nil || layoutGroup != nil else {
                // Nothing local to send; the flag is stale.
                projection.syncState = .synced
                projection.syncError = nil
                continue
            }

            let notebookId = projection.notebookId
            do {
                let remote = try await service.updateNotebookSettings(
                    id: notebookId, reviewPolicy: policyGroup, cardLayout: layoutGroup
                )
                guard projection.modelContext != nil else { continue }
                guard let settings = remote.settings else {
                    throw NotebookSettingsSyncError.serverDidNotReturnSettings
                }
                projection.applyRemote(settings)
            } catch {
                guard projection.modelContext != nil else { continue }
                projection.syncState = .failed
                projection.syncError = error.localizedDescription
            }
        }
        modelContext.safeSave()
    }
}

enum NotebookSettingsSyncError: LocalizedError {
    case serverDidNotReturnSettings

    var errorDescription: String? {
        switch self {
        case .serverDidNotReturnSettings:
            return L10n.string("notebookSettings.serverUnsupported")
        }
    }
}

/// One optimistic PATCH per settings group. Review policy and card layout keep
/// independent generation counters: a newer save of one group supersedes only
/// older in-flight saves of that same group, so a failure (or success) of the
/// other group is never swallowed by an unrelated save.
@MainActor
final class NotebookSettingsSaver {
    enum Outcome {
        case applied(KGNotebookSettings)
        case failed(Error)
        /// A newer save of the same group owns the UI result.
        case superseded
    }

    private var policyGeneration = 0
    private var layoutGeneration = 0

    func saveReviewPolicy(
        projection: NotebookSettingsProjection,
        policy: ReviewPolicy?,
        updatedAt: Double,
        service: any NotebookServing
    ) async -> Outcome {
        policyGeneration += 1
        let generation = policyGeneration
        return await send(
            projection: projection,
            isCurrent: { [self] in generation == policyGeneration }
        ) {
            try await service.updateNotebookSettings(
                id: projection.notebookId,
                reviewPolicy: KGNotebookSettingsPatchGroup(
                    value: policy.map(KGNotebookReviewPolicy.init), updatedAt: updatedAt
                ),
                cardLayout: nil
            )
        }
    }

    func saveCardLayout(
        projection: NotebookSettingsProjection,
        profile: ReviewCardLayoutProfile?,
        updatedAt: Double,
        service: any NotebookServing
    ) async -> Outcome {
        layoutGeneration += 1
        let generation = layoutGeneration
        return await send(
            projection: projection,
            isCurrent: { [self] in generation == layoutGeneration }
        ) {
            try await service.updateNotebookSettings(
                id: projection.notebookId,
                reviewPolicy: nil,
                cardLayout: KGNotebookSettingsPatchGroup(
                    value: profile.map(KGNotebookCardLayout.init), updatedAt: updatedAt
                )
            )
        }
    }

    private func send(
        projection: NotebookSettingsProjection,
        isCurrent: () -> Bool,
        request: () async throws -> KGNotebook
    ) async -> Outcome {
        do {
            let remote = try await request()
            guard isCurrent() else { return .superseded }
            guard let settings = remote.settings else {
                throw NotebookSettingsSyncError.serverDidNotReturnSettings
            }
            projection.applyRemote(settings)
            return .applied(settings)
        } catch {
            guard isCurrent() else { return .superseded }
            // Keep the optimistic projection: it is the durable local state
            // review uses immediately, and retry replays the exact intent.
            projection.syncState = .failed
            projection.syncError = error.localizedDescription
            return .failed(error)
        }
    }
}
