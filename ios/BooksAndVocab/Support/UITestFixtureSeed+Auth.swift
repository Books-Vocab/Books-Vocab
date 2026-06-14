#if os(iOS)
import Foundation
import SwiftData

extension UITestFixtureSeed {
    /// Auth-flow fixtures. Two ids compose the tiered-access UX states:
    ///
    /// - `tieredCatalog` — a real podcast catalog (lab audio + word-level SRT)
    ///   with a previewable ep1 and a gated ep2, *without* logging in, plus an
    ///   emptied bookshelf so the guest login entry point is deterministic.
    ///   Launched alone (under `-isolatedAuthSession`) the app is a guest.
    /// - `signedIn` — injects an authenticated session via the real
    ///   `AuthManager.login` path. Combine with `tieredCatalog` to exercise
    ///   the free-tier (token, no Pro) side of the same catalog.
    @MainActor
    static func seedAuth(_ id: String, into container: ModelContainer) {
        switch id {
        case "guest":
            AppLog.app.info("UI-test fixture seeded: auth.guest")
        case "tieredCatalog":
            seedAuthTieredCatalog(into: container)
        case "signedIn":
            seedAuthSignedInSession()
        default:
            AppLog.app.warning("Unknown auth fixture ID: \(id)")
        }
    }

    @MainActor
    private static func seedAuthSignedInSession() {
        // 整段 simulator-gate（不只 login）：displayName/userEmail setter 也會
        // 被 login() 持久化進真實 UserDefaults，真機上一併拒絕。
        #if targetEnvironment(simulator)
        // Seed guard：非 isolated session（如 unit-test host app、漏帶旗標的
        // UI test）拒絕 seed —— 否則假 session 經真 AuthManager.login 落盤，
        // 殘留給後續正常模式啟動的 host app 拿去打生產（2026-06-11 401 事故）。
        guard AppRuntimeOptions.shouldUseIsolatedAuthSession() else {
            // UI test 帶 -ui-testing 卻漏 -isolatedAuthSession = launch helper 用錯，
            // 大聲失敗（否則 test 以訪客態繼續跑，下游 assert 難診斷）；
            // unit-test host app（無 -ui-testing）則靜默拒絕即可。
            if AppRuntimeOptions.isUITesting() {
                preconditionFailure("auth.signedIn fixture requires -isolatedAuthSession (use launchIsolatedApp)")
            }
            AppLog.app.error("UITestFixtureSeed: refused auth.signedIn without -isolatedAuthSession — fake session would persist into the real store")
            return
        }
        seedSignedInLoginFromWorld()
        AppLog.app.info("UI-test fixture seeded: auth.signedIn")
        #else
        AppLog.app.error("UITestFixtureSeed: refused auth.signedIn on physical device — would overwrite the real Keychain session")
        preconditionFailure("auth.signedIn fixture is simulator-only")
        #endif
    }

    @MainActor
    private static func seedAuthTieredCatalog(into container: ModelContainer) {
        let context = container.mainContext
        do {
            try clearAuthFixtureWorld(from: context)

            let fixture = try resolveAuthPodcastFixture()
            let audioURL = try copyAuthFixtureFile(
                source: fixture.audioURL,
                fileName: "kg-uitest-auth-\(fixture.audioURL.lastPathComponent)"
            )
            let subtitle = try String(contentsOf: fixture.subtitleURL, encoding: .utf8)

            let series = PodcastSeries(
                remoteId: fixture.seed.seriesRemoteId,
                title: fixture.seed.seriesTitle,
                hostNames: fixture.seed.hostNames
            )
            series.color = fixture.seed.color
            series.coverPattern = fixture.seed.coverPattern
            series.episodeCount = fixture.seed.episodes.count
            series.totalDurationSec = fixture.seed.episodes.reduce(0) { total, episode in
                total + (episode.durationSec ?? fixture.seed.durationSec)
            }
            series.sortOrder = fixture.seed.sortOrder ?? 0
            series.isFollowed = false

            for episodeSeed in fixture.seed.episodes {
                let episode = PodcastEpisode(
                    remoteId: episodeSeed.remoteId,
                    episodeNumber: episodeSeed.episodeNumber,
                    title: episodeSeed.title,
                    durationSec: episodeSeed.durationSec ?? fixture.seed.durationSec
                )
                episode.series = series
                episode.audioAvailable = episodeSeed.audioAvailable
                episode.previewAvailable = episodeSeed.previewAvailable
                episode.previewDurationSec = episodeSeed.previewDurationSec ?? 0
                episode.localAudioPath = audioURL.path
                episode.subtitleAvailable = episodeSeed.subtitleAvailable
                episode.inlineSubtitle = subtitle
                context.insert(episode)
            }

            context.insert(series)
            try context.save()
            AppLog.app.info("UI-test fixture seeded: auth.tieredCatalog")
        } catch {
            AppLog.app.error("Failed to seed auth fixture: \(error)")
        }
    }

    /// Reset the world this flow asserts on: podcast catalog (so tier gating is
    /// evaluated against exactly the seeded episodes) and bookshelf books (so
    /// the guest empty-state login entry point is deterministically visible).
    /// Mirrors `clearPodcastFixtures` in the podcast fixture, which is private
    /// to that flow's file by design (per-flow fixture ownership).
    @MainActor
    private static func clearAuthFixtureWorld(from context: ModelContext) throws {
        for progress in try context.fetch(FetchDescriptor<PodcastProgress>()) {
            context.delete(progress)
        }
        for episode in try context.fetch(FetchDescriptor<PodcastEpisode>()) {
            context.delete(episode)
        }
        for series in try context.fetch(FetchDescriptor<PodcastSeries>()) {
            context.delete(series)
        }
        for book in try context.fetch(FetchDescriptor<Book>()) {
            context.delete(book)
        }
        try context.save()
    }

    private struct AuthPodcastFixture {
        let seed: UIWorldRuntimePodcastSeed
        let audioURL: URL
        let subtitleURL: URL
    }

    /// Same UI World-owned asset domain as the podcast playable preview.
    private static func resolveAuthPodcastFixture() throws -> AuthPodcastFixture {
        let seed = FixtureDatasetStore.requireRuntimePodcastSeed(for: .tieredCatalog)
        let audioURL = try FixtureDatasetStore.requireAssetURL(ref: seed.audioAssetRef)
        let subtitleURL = try FixtureDatasetStore.requireAssetURL(ref: seed.subtitleAssetRef)
        return AuthPodcastFixture(seed: seed, audioURL: audioURL, subtitleURL: subtitleURL)
    }

    private static func copyAuthFixtureFile(source: URL, fileName: String) throws -> URL {
        let destination = FileManager.default.temporaryDirectory.appendingPathComponent(fileName)
        if FileManager.default.fileExists(atPath: destination.path) {
            try FileManager.default.removeItem(at: destination)
        }
        try FileManager.default.copyItem(at: source, to: destination)
        return destination
    }
}
#endif
