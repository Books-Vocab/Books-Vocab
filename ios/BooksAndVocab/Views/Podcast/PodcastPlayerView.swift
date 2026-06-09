#if os(iOS)
import SwiftUI
import SwiftData

struct PodcastPlayerView: View {
    let episodeId: String
    var body: some View {
        PodcastPlayerScene(episodeId: episodeId)
    }

    static func fetchEpisode(remoteId: String, in context: ModelContext) -> PodcastEpisode? {
        PodcastPlayerSupport.fetchEpisode(remoteId: remoteId, in: context)
    }

    static func resolveVocabularyContext(
        episodeId: String,
        modelContext: ModelContext,
        rawNotebookId: String,
        toastCoordinator: AppToastCoordinator,
        vocabulary: [VocabularyEntry]
    ) -> PodcastVocabularyContext? {
        PodcastPlayerSupport.resolveVocabularyContext(
            episodeId: episodeId,
            modelContext: modelContext,
            rawNotebookId: rawNotebookId,
            toastCoordinator: toastCoordinator,
            vocabulary: vocabulary
        )
    }

    static func shouldPersist(
        currentTime: TimeInterval,
        reason: PodcastProgressPushState.Reason
    ) -> Bool {
        PodcastPlayerSupport.shouldPersist(
            currentTime: currentTime,
            reason: reason
        )
    }

    static func isCompleted(currentTime: TimeInterval, duration: TimeInterval, isReady: Bool) -> Bool {
        PodcastPlayerSupport.isCompleted(
            currentTime: currentTime,
            duration: duration,
            isReady: isReady
        )
    }
}
#endif
