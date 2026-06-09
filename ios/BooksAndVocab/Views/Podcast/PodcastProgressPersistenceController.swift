#if os(iOS)
import Foundation
import SwiftData

@MainActor
final class PodcastProgressPersistenceController {
    private var lastSavedTime: TimeInterval = 0
    private var pushState = PodcastProgressPushState()

    func reset() {
        lastSavedTime = 0
        pushState = PodcastProgressPushState()
    }

    func saveIfNeeded(
        time: TimeInterval,
        viewModel: PodcastPlayerViewModel,
        episodeRemoteId: String,
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        guard abs(time - lastSavedTime) > 10 else { return }
        lastSavedTime = time
        save(
            viewModel: viewModel,
            episodeRemoteId: episodeRemoteId,
            modelContext: modelContext,
            kgService: kgService,
            reason: .tick
        )
    }

    func save(
        viewModel: PodcastPlayerViewModel,
        episodeRemoteId: String,
        modelContext: ModelContext,
        kgService: any KGServing,
        reason: PodcastProgressPushState.Reason = .pause
    ) {
        saveSnapshot(
            currentTime: viewModel.currentTime,
            duration: viewModel.duration,
            isCompleted: (
                viewModel.state == .ready
                && viewModel.duration > 0
                && viewModel.currentTime >= viewModel.duration - 1
            ),
            episodeRemoteId: episodeRemoteId,
            modelContext: modelContext,
            kgService: kgService,
            reason: reason
        )
    }

    func saveSnapshot(
        currentTime: TimeInterval,
        duration: TimeInterval,
        isCompleted: Bool,
        episodeRemoteId: String,
        modelContext: ModelContext,
        kgService: any KGServing,
        reason: PodcastProgressPushState.Reason = .pause
    ) {
        guard Self.shouldPersist(currentTime: currentTime, reason: reason) else { return }
        let targetId = episodeRemoteId
        let descriptor = FetchDescriptor<PodcastProgress>(
            predicate: #Predicate { $0.episodeRemoteId == targetId },
            sortBy: [SortDescriptor(\.updatedAt, order: .reverse)]
        )
        let existing = (try? modelContext.fetch(descriptor)) ?? []
        for stale in existing.dropFirst() {
            modelContext.delete(stale)
        }

        let progress: PodcastProgress
        if let newest = existing.first {
            progress = newest
        } else {
            progress = PodcastProgress(episodeRemoteId: episodeRemoteId)
            modelContext.insert(progress)
        }

        let now = Date()
        progress.lastPlayedTime = currentTime
        progress.completed = isCompleted
        progress.updatedAt = now
        do {
            try modelContext.save()
        } catch {
            AppLog.app.error("PodcastProgress save failed: \(error.localizedDescription)")
        }

        let shouldPush = pushState.shouldPush(
            position: currentTime,
            duration: duration,
            now: now,
            reason: reason
        )
        guard shouldPush,
              let parsed = PodcastSyncService.parseEpisodeRemoteId(episodeRemoteId) else { return }
        let captured = (
            seriesId: parsed.seriesId,
            episodeNumber: parsed.episodeNumber,
            positionSec: currentTime,
            durationSec: duration,
            updatedAt: now
        )
        let service = PodcastSyncService(kgService: kgService)
        Task.detached(priority: .utility) {
            do {
                try await service.pushProgress(
                    seriesId: captured.seriesId,
                    episodeNumber: captured.episodeNumber,
                    positionSec: captured.positionSec,
                    durationSec: captured.durationSec,
                    updatedAt: captured.updatedAt
                )
            } catch {
                AppLog.kg.warning("[PodcastSync] progress push failed: \(error.localizedDescription)")
            }
        }
    }

    /// Decides whether a `position == 0` write is meaningful.
    ///
    /// A `.tick` at position 0 is pure noise (audio not advanced yet) and must
    /// be dropped. But an explicit `.pause` / `.episodeSwitch` at position 0 is
    /// a real user-visible transition that must persist.
    static func shouldPersist(
        currentTime: TimeInterval,
        reason: PodcastProgressPushState.Reason
    ) -> Bool {
        if currentTime == 0 && reason == .tick { return false }
        return true
    }
}
#endif
