#if os(iOS)
import Foundation
import Observation
import SwiftData
import SwiftUI

struct PodcastEpisodeProgressSnapshot: Equatable {
    let currentTime: TimeInterval
    let duration: TimeInterval
    let isCompleted: Bool
    let episodeRemoteId: String
}

enum PodcastEpisodeSessionLoadOutcome: Equatable {
    case loaded(
        plan: PodcastPlayerLoadPlan,
        subtitle: PodcastPlayerResolvedSubtitle,
        audioHeaders: [String: String]
    )
    case missingAudio
    case authorizationFailed(String)
    case cancelled
}

@MainActor
protocol PodcastEpisodeSessionLoading: AnyObject {
    func makeViewModel(for episode: PodcastEpisode) -> PodcastPlayerViewModel

    func load(
        episode: PodcastEpisode,
        kgService: any AuthTokenProviding
    ) async -> PodcastEpisodeSessionLoadOutcome

    func retrySubtitle(
        for episode: PodcastEpisode,
        kgService: any AuthTokenProviding
    ) async -> String?
}

@MainActor
protocol PodcastEpisodeSessionPreviewLoading: AnyObject {
    func loadCatalogPreview(
        _ preview: PodcastPlayerCatalogPreview,
        into viewModel: PodcastPlayerViewModel
    )
}

@MainActor
protocol PodcastEpisodeSessionProgressStoring: AnyObject {
    func reset()

    func initialProgressTime(
        for episodeRemoteId: String,
        modelContext: ModelContext
    ) -> TimeInterval?

    func saveIfNeeded(
        snapshot: PodcastEpisodeProgressSnapshot,
        modelContext: ModelContext,
        kgService: any KGServing
    )

    func save(
        snapshot: PodcastEpisodeProgressSnapshot,
        modelContext: ModelContext,
        kgService: any KGServing,
        reason: PodcastProgressPushState.Reason
    )
}

@MainActor
protocol PodcastEpisodeSessionQueueing {
    func nextEpisode(
        in episodes: [PodcastEpisode],
        after current: PodcastEpisode,
        tier: PodcastTier
    ) -> PodcastEpisode?
}

@MainActor
final class PodcastEpisodeSessionLoader: PodcastEpisodeSessionLoading
    , PodcastEpisodeSessionPreviewLoading
{
    func makeViewModel(for episode: PodcastEpisode) -> PodcastPlayerViewModel {
        PodcastPlayerViewModel(hostNames: episode.series?.hostNames ?? [])
    }

    func load(
        episode: PodcastEpisode,
        kgService: any AuthTokenProviding
    ) async -> PodcastEpisodeSessionLoadOutcome {
        guard let plan = PodcastPlayerLoadPlan.make(episode: episode) else {
            return .missingAudio
        }

        let resolvedSubtitle = await PodcastPlayerLoader.resolveSubtitle(
            from: plan.subtitleSource,
            kgService: kgService
        )
        if Task.isCancelled { return .cancelled }

        let audioHeaders: [String: String]
        do {
            audioHeaders = try await PodcastPlayerLoader.resolveAudioHeaders(
                for: plan,
                kgService: kgService
            )
        } catch is CancellationError {
            return .cancelled
        } catch {
            return .authorizationFailed(error.localizedDescription)
        }
        if Task.isCancelled { return .cancelled }

        return .loaded(
            plan: plan,
            subtitle: resolvedSubtitle,
            audioHeaders: audioHeaders
        )
    }

    func retrySubtitle(
        for episode: PodcastEpisode,
        kgService: any AuthTokenProviding
    ) async -> String? {
        guard let subtitleURL = episode.subtitleURL else { return nil }
        return await PodcastPlayerLoader.fetchSubtitle(
            urlString: subtitleURL,
            kgService: kgService
        )
    }

    func loadCatalogPreview(
        _ preview: PodcastPlayerCatalogPreview,
        into viewModel: PodcastPlayerViewModel
    ) {
        viewModel.catalogReadyPreview(
            duration: preview.durationSec,
            currentTime: preview.currentSec,
            subtitleSRT: preview.subtitleSRT
        )
    }
}

@MainActor
final class PodcastEpisodeSessionProgressStore: PodcastEpisodeSessionProgressStoring {
    private var persistence = PodcastProgressPersistenceController()
    private var lastSavedTime: TimeInterval = 0

    func reset() {
        lastSavedTime = 0
        persistence.reset()
    }

    func initialProgressTime(
        for episodeRemoteId: String,
        modelContext: ModelContext
    ) -> TimeInterval? {
        let targetId = episodeRemoteId
        let descriptor = FetchDescriptor<PodcastProgress>(
            predicate: #Predicate { $0.episodeRemoteId == targetId },
            sortBy: [SortDescriptor(\.updatedAt, order: .reverse)]
        )
        guard let progress = try? modelContext.fetch(descriptor).first,
              progress.lastPlayedTime > 0,
              !progress.completed else {
            return nil
        }
        return progress.lastPlayedTime
    }

    func saveIfNeeded(
        snapshot: PodcastEpisodeProgressSnapshot,
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        guard abs(snapshot.currentTime - lastSavedTime) > 10 else { return }
        lastSavedTime = snapshot.currentTime
        persistence.saveSnapshot(
            currentTime: snapshot.currentTime,
            duration: snapshot.duration,
            isCompleted: snapshot.isCompleted,
            episodeRemoteId: snapshot.episodeRemoteId,
            modelContext: modelContext,
            kgService: kgService,
            reason: .tick
        )
    }

    func save(
        snapshot: PodcastEpisodeProgressSnapshot,
        modelContext: ModelContext,
        kgService: any KGServing,
        reason: PodcastProgressPushState.Reason
    ) {
        persistence.saveSnapshot(
            currentTime: snapshot.currentTime,
            duration: snapshot.duration,
            isCompleted: snapshot.isCompleted,
            episodeRemoteId: snapshot.episodeRemoteId,
            modelContext: modelContext,
            kgService: kgService,
            reason: reason
        )
    }
}

@MainActor
struct PodcastEpisodeSessionQueue: PodcastEpisodeSessionQueueing {
    func nextEpisode(
        in episodes: [PodcastEpisode],
        after current: PodcastEpisode,
        tier: PodcastTier
    ) -> PodcastEpisode? {
        PodcastQueue.nextPlayable(in: episodes, after: current, tier: tier)
    }
}

@MainActor @Observable
final class PodcastEpisodeSessionController {
    private(set) var viewModel: PodcastPlayerViewModel?
    private(set) var loadedEpisodeId: String?
    private(set) var loadAttemptedEpisodeId: String?
    private(set) var progressBootstrapCompleted = false
    private(set) var isLoading = false

    private let loader: any PodcastEpisodeSessionLoading
    private let progressStore: any PodcastEpisodeSessionProgressStoring
    private let queue: any PodcastEpisodeSessionQueueing
    private var loadTask: Task<Void, Never>?
    private var loadGeneration = 0
    private var baseEpisodeId: String?
    private var overrideEpisodeId: String?
    private var lifecyclePersisted: Set<LifecyclePersistenceKey> = []
    private var didDisappear = false

    private struct LifecyclePersistenceKey: Hashable {
        enum Event: Hashable {
            case background
            case disappear
        }

        let episodeId: String
        let event: Event
    }

    var activeEpisodeId: String? {
        overrideEpisodeId ?? baseEpisodeId
    }

    init(
        loader: (any PodcastEpisodeSessionLoading)? = nil,
        progressStore: (any PodcastEpisodeSessionProgressStoring)? = nil,
        queue: (any PodcastEpisodeSessionQueueing)? = nil
    ) {
        self.loader = loader ?? PodcastEpisodeSessionLoader()
        self.progressStore = progressStore ?? PodcastEpisodeSessionProgressStore()
        self.queue = queue ?? PodcastEpisodeSessionQueue()
    }

    func load(
        episode: PodcastEpisode,
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        load(
            episode: episode,
            modelContext: modelContext,
            kgService: kgService,
            force: false
        )
    }

    func reloadEpisode(
        episode: PodcastEpisode,
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        load(
            episode: episode,
            modelContext: modelContext,
            kgService: kgService,
            force: true
        )
    }

#if DEBUG
    func load(
        episode: PodcastEpisode,
        modelContext: ModelContext,
        kgService: any KGServing,
        catalogPreview: PodcastPlayerCatalogPreview?
    ) {
        load(
            episode: episode,
            modelContext: modelContext,
            kgService: kgService,
            force: false,
            catalogPreview: catalogPreview
        )
    }
#endif

    private func load(
        episode: PodcastEpisode,
        modelContext: ModelContext,
        kgService: any KGServing,
        force: Bool,
        catalogPreview: PodcastPlayerCatalogPreview? = nil
    ) {
        guard force || loadedEpisodeId != episode.remoteId else { return }
        didDisappear = false
        lifecyclePersisted.removeAll()
        if baseEpisodeId == nil { baseEpisodeId = episode.remoteId }

        if let oldViewModel = viewModel,
           let oldEpisodeId = loadedEpisodeId,
           oldEpisodeId != episode.remoteId {
            save(
                viewModel: oldViewModel,
                episodeRemoteId: oldEpisodeId,
                modelContext: modelContext,
                kgService: kgService,
                reason: .episodeSwitch
            )
        }

        cancelLoad()
        viewModel?.stop()
        loadGeneration &+= 1
        let generation = loadGeneration
        let viewModel = loader.makeViewModel(for: episode)
        self.viewModel = viewModel
        loadedEpisodeId = episode.remoteId
        loadAttemptedEpisodeId = episode.remoteId
        progressBootstrapCompleted = false
        isLoading = true
        progressStore.reset()
        let initialProgressTime = progressStore.initialProgressTime(
            for: episode.remoteId,
            modelContext: modelContext
        )

        if let plan = PodcastPlayerLoadPlan.make(episode: episode),
           case .remote = plan.subtitleSource {
            viewModel.setSubtitleLoading()
        }

        loadTask = Task { [weak self, weak viewModel] in
            guard let self, let viewModel else { return }
#if DEBUG
            if let catalogPreview,
               let previewLoader = self.loader as? any PodcastEpisodeSessionPreviewLoading {
                previewLoader.loadCatalogPreview(catalogPreview, into: viewModel)
                guard self.isCurrent(
                    generation: generation,
                    episodeId: episode.remoteId,
                    viewModel: viewModel
                ) else { return }
                self.isLoading = false
                self.loadTask = nil
                return
            }
#endif
            let outcome = await self.loader.load(episode: episode, kgService: kgService)
            guard !Task.isCancelled,
                  self.isCurrent(
                    generation: generation,
                    episodeId: episode.remoteId,
                    viewModel: viewModel
                  ) else {
                return
            }

            switch outcome {
            case .loaded(let plan, let subtitle, let audioHeaders):
                switch subtitle {
                case .content:
                    break
                case .unavailable:
                    viewModel.markSubtitleUnavailable()
                case .failed:
                    viewModel.markSubtitleFailed()
                }
                viewModel.loadEpisode(
                    audioURL: plan.audioURL,
                    subtitleContent: {
                        if case .content(let content) = subtitle { return content }
                        return nil
                    }(),
                    title: plan.title,
                    audioHTTPHeaders: audioHeaders,
                    prefetchedDurationSec: plan.durationSec,
                    initialProgressTime: initialProgressTime
                )
            case .missingAudio:
                viewModel.reportError(L10n.string("無音訊 URL"))
            case .authorizationFailed(let message):
                viewModel.reportError(L10n.format("無法取得認證 token：%@", message))
            case .cancelled:
                return
            }
            self.isLoading = false
            self.loadTask = nil
        }
    }

    func markLoadAttempted(for episodeId: String) {
        if baseEpisodeId == nil { baseEpisodeId = episodeId }
        loadAttemptedEpisodeId = episodeId
    }

    func retrySubtitle(
        episode: PodcastEpisode,
        kgService: any KGServing
    ) {
        guard let viewModel,
              loadedEpisodeId == episode.remoteId else { return }
        let generation = loadGeneration
        viewModel.setSubtitleLoading()
        Task { [weak self, weak viewModel] in
            guard let self, let viewModel else { return }
            let content = await self.loader.retrySubtitle(
                for: episode,
                kgService: kgService
            )
            guard !Task.isCancelled,
                  self.isCurrent(
                      generation: generation,
                      episodeId: episode.remoteId,
                      viewModel: viewModel
                  ) else { return }
            if let content {
                viewModel.applySubtitle(content: content)
            } else {
                viewModel.markSubtitleFailed()
            }
        }
    }

    func nextEpisode(
        in series: PodcastSeries,
        after current: PodcastEpisode,
        tier: PodcastTier
    ) {
        guard let next = queue.nextEpisode(in: series.episodes, after: current, tier: tier) else {
            return
        }
        overrideEpisodeId = next.remoteId
    }

    func handleProgressTick(
        _ time: TimeInterval,
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        guard let viewModel,
              let loadedEpisodeId,
              loadedEpisodeId == activeEpisodeId else { return }
        progressStore.saveIfNeeded(
            snapshot: snapshot(
                viewModel: viewModel,
                episodeRemoteId: loadedEpisodeId,
                timeOverride: time
            ),
            modelContext: modelContext,
            kgService: kgService
        )
    }

    func handlePlayerState(
        _ state: PodcastPlayerState,
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        guard let viewModel else { return }
        if state == .ready, !progressBootstrapCompleted {
            progressBootstrapCompleted = true
            return
        }
        guard state == .paused || state == .ready,
              let loadedEpisodeId,
              loadedEpisodeId == activeEpisodeId else { return }
        save(
            viewModel: viewModel,
            episodeRemoteId: loadedEpisodeId,
            modelContext: modelContext,
            kgService: kgService,
            reason: .pause
        )
    }

    func handleScenePhase(
        _ phase: ScenePhase,
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        guard phase != .active else { return }
        persistLifecycle(
            .background,
            modelContext: modelContext,
            kgService: kgService
        )
    }

    func handleDisappear(
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        guard !didDisappear else { return }
        didDisappear = true
        persistLifecycle(
            .disappear,
            modelContext: modelContext,
            kgService: kgService
        )
        cancelLoad()
        loadGeneration &+= 1
        viewModel?.shutdown()
        viewModel = nil
        loadedEpisodeId = nil
        loadAttemptedEpisodeId = nil
        progressBootstrapCompleted = false
        isLoading = false
    }

    private func persistLifecycle(
        _ event: LifecyclePersistenceKey.Event,
        modelContext: ModelContext,
        kgService: any KGServing
    ) {
        guard let viewModel,
              let loadedEpisodeId,
              loadedEpisodeId == activeEpisodeId,
              !(!progressBootstrapCompleted && viewModel.currentTime == 0) else {
            return
        }
        let key = LifecyclePersistenceKey(episodeId: loadedEpisodeId, event: event)
        guard lifecyclePersisted.insert(key).inserted else { return }
        save(
            viewModel: viewModel,
            episodeRemoteId: loadedEpisodeId,
            modelContext: modelContext,
            kgService: kgService,
            reason: .pause
        )
    }

    private func save(
        viewModel: PodcastPlayerViewModel,
        episodeRemoteId: String,
        modelContext: ModelContext,
        kgService: any KGServing,
        reason: PodcastProgressPushState.Reason
    ) {
        progressStore.save(
            snapshot: snapshot(viewModel: viewModel, episodeRemoteId: episodeRemoteId),
            modelContext: modelContext,
            kgService: kgService,
            reason: reason
        )
    }

    private func snapshot(
        viewModel: PodcastPlayerViewModel,
        episodeRemoteId: String,
        timeOverride: TimeInterval? = nil
    ) -> PodcastEpisodeProgressSnapshot {
        let time = timeOverride ?? viewModel.currentTime
        return PodcastEpisodeProgressSnapshot(
            currentTime: time,
            duration: viewModel.duration,
            isCompleted: PodcastPlayerSupport.isCompleted(
                currentTime: time,
                duration: viewModel.duration,
                isReady: viewModel.state == .ready
            ),
            episodeRemoteId: episodeRemoteId
        )
    }

    private func cancelLoad() {
        loadTask?.cancel()
        loadTask = nil
    }

    private func isCurrent(
        generation: Int,
        episodeId: String,
        viewModel: PodcastPlayerViewModel
    ) -> Bool {
        generation == loadGeneration
            && loadedEpisodeId == episodeId
            && self.viewModel === viewModel
    }
}
#endif
