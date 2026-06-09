#if os(iOS)
import SwiftData
import Foundation

@MainActor
enum PodcastPlayerSupport {
    static func fetchEpisode(remoteId: String, in context: ModelContext) -> PodcastEpisode? {
        let target = remoteId
        let descriptor = FetchDescriptor<PodcastEpisode>(
            predicate: #Predicate { $0.remoteId == target }
        )
        return try? context.fetch(descriptor).first
    }

    static func resolveVocabularyContext(
        episodeId: String,
        modelContext: ModelContext,
        rawNotebookId: String,
        toastCoordinator: AppToastCoordinator,
        vocabulary: [VocabularyEntry]
    ) -> PodcastVocabularyContext? {
        guard let episode = fetchEpisode(remoteId: episodeId, in: modelContext),
              let series = episode.series else { return nil }
        let nbId = VocabularyEntry.resolveNotebookId(rawNotebookId, in: modelContext)
        return PodcastVocabularyContext(
            vocabulary: vocabulary,
            modelContext: modelContext,
            series: series,
            episode: episode,
            notebookId: nbId,
            toastCoordinator: toastCoordinator
        )
    }

    static func shouldPersist(
        currentTime: TimeInterval,
        reason: PodcastProgressPushState.Reason
    ) -> Bool {
        PodcastProgressPersistenceController.shouldPersist(
            currentTime: currentTime,
            reason: reason
        )
    }

    static func isCompleted(currentTime: TimeInterval, duration: TimeInterval, isReady: Bool) -> Bool {
        isReady && duration > 0 && currentTime >= duration - 1
    }
}
#endif
