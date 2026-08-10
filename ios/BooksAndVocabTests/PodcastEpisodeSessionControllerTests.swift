#if os(iOS)
import Foundation
import SwiftData
import SwiftUI
import Testing
@testable import BooksAndVocab

@Suite("PodcastEpisodeSessionController")
@MainActor
struct PodcastEpisodeSessionControllerTests {
    @Test
    func switchingEpisodesCancelsTheOldLoad() async throws {
        let loader = FakeSessionLoader()
        let store = FakeProgressStore()
        let controller = PodcastEpisodeSessionController(
            loader: loader,
            progressStore: store,
            queue: FakeEpisodeQueue()
        )
        let context = try makeContext()
        let kgService = KGService()
        let first = makeEpisode(id: "series_ep_1", number: 1)
        let second = makeEpisode(id: "series_ep_2", number: 2)

        controller.load(episode: first, modelContext: context, kgService: kgService)
        await settle()
        controller.load(episode: second, modelContext: context, kgService: kgService)
        await settle()

        loader.resolve(
            episodeId: first.remoteId,
            outcome: .loaded(
                plan: makePlan(for: first),
                subtitle: .content("first"),
                audioHeaders: [:]
            )
        )
        loader.resolve(
            episodeId: second.remoteId,
            outcome: .loaded(
                plan: makePlan(for: second),
                subtitle: .content("second"),
                audioHeaders: [:]
            )
        )
        await settle()

        #expect(loader.startedEpisodeIds == [first.remoteId, second.remoteId])
        #expect(loader.cancelledEpisodeIds == [first.remoteId])
        #expect(controller.loadedEpisodeId == second.remoteId)
        #expect(controller.viewModel === loader.viewModels[second.remoteId])
    }

    @Test
    func staleLoadCompletionCannotWriteBackToTheCurrentSession() async throws {
        let loader = FakeSessionLoader()
        let store = FakeProgressStore()
        let controller = PodcastEpisodeSessionController(
            loader: loader,
            progressStore: store,
            queue: FakeEpisodeQueue()
        )
        let context = try makeContext()
        let kgService = KGService()
        let first = makeEpisode(id: "series_ep_1", number: 1)
        let second = makeEpisode(id: "series_ep_2", number: 2)

        controller.load(episode: first, modelContext: context, kgService: kgService)
        await settle()
        controller.load(episode: second, modelContext: context, kgService: kgService)
        await settle()
        let savesBeforeStaleCompletion = store.savedEpisodeIds

        loader.resolve(
            episodeId: first.remoteId,
            outcome: .loaded(
                plan: makePlan(for: first),
                subtitle: .failed,
                audioHeaders: [:]
            )
        )
        await settle()

        #expect(controller.loadedEpisodeId == second.remoteId)
        #expect(controller.viewModel === loader.viewModels[second.remoteId])
        #expect(controller.viewModel?.subtitleState == .idle)
        #expect(store.savedEpisodeIds == savesBeforeStaleCompletion)
    }

    @Test
    func subtitleFailureIsVisibleWithoutBlockingAudioSetup() async throws {
        let loader = FakeSessionLoader()
        let controller = PodcastEpisodeSessionController(
            loader: loader,
            progressStore: FakeProgressStore(),
            queue: FakeEpisodeQueue()
        )
        let context = try makeContext()
        let kgService = KGService()
        let episode = makeEpisode(id: "series_ep_1", number: 1)

        controller.load(episode: episode, modelContext: context, kgService: kgService)
        await settle()
        loader.resolve(
            episodeId: episode.remoteId,
            outcome: .loaded(
                plan: makePlan(for: episode),
                subtitle: .failed,
                audioHeaders: [:]
            )
        )
        await settle()

        #expect(controller.viewModel?.subtitleState == .failed)
        #expect(controller.viewModel?.state == .loading)
        #expect(loader.audioEngines[episode.remoteId]?.loadCount == 1)
    }

    @Test
    func backgroundAndDisappearEachPersistAtMostOnce() async throws {
        let loader = FakeSessionLoader()
        let store = FakeProgressStore()
        let controller = PodcastEpisodeSessionController(
            loader: loader,
            progressStore: store,
            queue: FakeEpisodeQueue()
        )
        let context = try makeContext()
        let kgService = KGService()
        let episode = makeEpisode(id: "series_ep_1", number: 1)

        controller.load(episode: episode, modelContext: context, kgService: kgService)
        await settle()
        loader.resolve(
            episodeId: episode.remoteId,
            outcome: .loaded(
                plan: makePlan(for: episode),
                subtitle: .content("subtitle"),
                audioHeaders: [:]
            )
        )
        await settle()
        loader.audioEngines[episode.remoteId]?.emitReady()
        loader.audioEngines[episode.remoteId]?.emitTimeUpdate(12)
        controller.handlePlayerState(.ready, modelContext: context, kgService: kgService)

        controller.handleScenePhase(.background, modelContext: context, kgService: kgService)
        controller.handleScenePhase(.background, modelContext: context, kgService: kgService)
        controller.handleDisappear(modelContext: context, kgService: kgService)
        controller.handleDisappear(modelContext: context, kgService: kgService)

        #expect(store.savedEpisodeIds == [episode.remoteId, episode.remoteId])
    }

    private func makeEpisode(id: String, number: Int) -> PodcastEpisode {
        PodcastEpisode(remoteId: id, episodeNumber: number, title: "Episode", durationSec: 100)
    }

    private func makePlan(for episode: PodcastEpisode) -> PodcastPlayerLoadPlan {
        PodcastPlayerLoadPlan(
            audioURL: URL(string: "https://example.com/\(episode.remoteId).m4a")!,
            usesLocalAudio: false,
            subtitleSource: .inline("subtitle"),
            title: episode.displayTitle,
            durationSec: episode.durationSec
        )
    }

    private func makeContext() throws -> ModelContext {
        let configuration = ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        let container = try ModelContainer(
            for: PodcastSeries.self,
            PodcastEpisode.self,
            PodcastProgress.self,
            configurations: configuration
        )
        return ModelContext(container)
    }

    private func settle() async {
        for _ in 0..<8 {
            await Task.yield()
        }
    }
}

@MainActor
private final class FakeSessionLoader: PodcastEpisodeSessionLoading {
    private(set) var startedEpisodeIds: [String] = []
    private(set) var cancelledEpisodeIds: [String] = []
    private var continuations: [String: CheckedContinuation<PodcastEpisodeSessionLoadOutcome, Never>] = [:]
    private(set) var viewModels: [String: PodcastPlayerViewModel] = [:]
    private(set) var audioEngines: [String: FakeAudioEngine] = [:]

    func makeViewModel(for episode: PodcastEpisode) -> PodcastPlayerViewModel {
        let audio = FakeAudioEngine()
        let viewModel = PodcastPlayerViewModel(
            hostNames: episode.series?.hostNames ?? [],
            audioEngine: audio,
            subtitleEngine: FakeSubtitleEngine()
        )
        viewModels[episode.remoteId] = viewModel
        audioEngines[episode.remoteId] = audio
        return viewModel
    }

    func load(
        episode: PodcastEpisode,
        kgService: any AuthTokenProviding
    ) async -> PodcastEpisodeSessionLoadOutcome {
        startedEpisodeIds.append(episode.remoteId)
        let outcome = await withCheckedContinuation { continuation in
            continuations[episode.remoteId] = continuation
        }
        if Task.isCancelled {
            cancelledEpisodeIds.append(episode.remoteId)
            return .cancelled
        }
        return outcome
    }

    func retrySubtitle(
        for episode: PodcastEpisode,
        kgService: any AuthTokenProviding
    ) async -> String? {
        nil
    }

    func resolve(episodeId: String, outcome: PodcastEpisodeSessionLoadOutcome) {
        continuations.removeValue(forKey: episodeId)?.resume(returning: outcome)
    }
}

@MainActor
private final class FakeProgressStore: PodcastEpisodeSessionProgressStoring {
    private(set) var savedEpisodeIds: [String] = []

    func reset() {}

    func initialProgressTime(
        for episodeRemoteId: String,
        modelContext: ModelContext
    ) -> TimeInterval? {
        nil
    }

    func saveIfNeeded(
        snapshot: PodcastEpisodeProgressSnapshot,
        modelContext: ModelContext,
        kgService: any KGServing
    ) {}

    func save(
        snapshot: PodcastEpisodeProgressSnapshot,
        modelContext: ModelContext,
        kgService: any KGServing,
        reason: PodcastProgressPushState.Reason
    ) {
        savedEpisodeIds.append(snapshot.episodeRemoteId)
    }
}

@MainActor
private struct FakeEpisodeQueue: PodcastEpisodeSessionQueueing {
    func nextEpisode(
        in episodes: [PodcastEpisode],
        after current: PodcastEpisode,
        tier: PodcastTier
    ) -> PodcastEpisode? {
        nil
    }
}

@MainActor
private final class FakeAudioEngine: PodcastAudioPlaying {
    var playbackRate: Float = 1
    var duration: TimeInterval = 100
    var currentTime: TimeInterval = 0
    var isPlaying = false
    private(set) var loadCount = 0

    var onTimeUpdate: ((TimeInterval) -> Void)?
    var onPlaybackFinished: (() -> Void)?
    var onDurationLoaded: ((TimeInterval) -> Void)?
    var onReadyToPlay: (() -> Void)?
    var onLoadFailed: ((String) -> Void)?
    var onBufferedEndChanged: ((TimeInterval) -> Void)?
    var onSystemPause: (() -> Void)?
    var onSystemResume: (() -> Void)?

    func loadAudio(
        url: URL,
        httpHeaders: [String: String],
        prefetchedDuration: TimeInterval?
    ) {
        loadCount += 1
    }

    func configureNowPlaying(title: String, artist: String) {}
    func play() { isPlaying = true }
    func pause() { isPlaying = false }
    func stop() { isPlaying = false }
    func shutdown() { isPlaying = false }

    func seek(to time: TimeInterval, autoResume: Bool) {
        currentTime = time
        isPlaying = autoResume
    }

    func setRate(_ rate: Float) { playbackRate = rate }

    func emitReady() { onReadyToPlay?() }

    func emitTimeUpdate(_ time: TimeInterval) {
        currentTime = time
        onTimeUpdate?(time)
    }
}

@MainActor
private final class FakeSubtitleEngine: PodcastSubtitling {
    var sentences: [PodcastSentence] = []

    func load(srtContent: String) {}

    func currentSentence(at time: TimeInterval) -> PodcastSentence? {
        sentences.first { $0.startTime <= time && time < $0.endTime }
    }
}
#endif
