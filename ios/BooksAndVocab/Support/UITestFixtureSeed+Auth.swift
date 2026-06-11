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
                assertionFailure("auth.signedIn fixture requires -isolatedAuthSession (use launchIsolatedApp)")
            }
            AppLog.app.error("UITestFixtureSeed: refused auth.signedIn without -isolatedAuthSession — fake session would persist into the real store")
            return
        }
        let auth = AuthManager.shared
        // Profile first — login() persists the current displayName/userEmail.
        auth.displayName = "UI Auth Tester"
        auth.userEmail = "ui-auth-tester@example.com"
        auth.login(userId: "ui-auth-user", token: "ui-auth-user-token")
        AppLog.app.info("UI-test fixture seeded: auth.signedIn")
        #else
        AppLog.app.error("UITestFixtureSeed: refused auth.signedIn on physical device — would overwrite the real Keychain session")
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
                remoteId: "ui-auth-series",
                title: "Atomic Habits (Auth Probe)",
                hostNames: ["Lab Podcast"]
            )
            series.color = "sunset"
            series.coverPattern = "waves"
            series.episodeCount = 2
            series.totalDurationSec = fixture.durationSec * 2
            series.sortOrder = -10_000
            series.isFollowed = false

            // Ep1: previewable — free tier may open it, a guest may not.
            let episode1 = PodcastEpisode(
                remoteId: "ui-auth-series_ep_01",
                episodeNumber: 1,
                title: "Tiered Access Preview Episode",
                durationSec: fixture.durationSec
            )
            episode1.series = series
            episode1.audioAvailable = true
            episode1.previewAvailable = true
            episode1.previewDurationSec = min(fixture.durationSec, 180)
            episode1.localAudioPath = audioURL.path
            episode1.subtitleAvailable = true
            episode1.inlineSubtitle = subtitle

            // Ep2: gated for guest AND free — only Pro plays it.
            let episode2 = PodcastEpisode(
                remoteId: "ui-auth-series_ep_02",
                episodeNumber: 2,
                title: "Tiered Access Gated Episode",
                durationSec: fixture.durationSec
            )
            episode2.series = series
            episode2.audioAvailable = true
            episode2.localAudioPath = audioURL.path
            episode2.subtitleAvailable = true
            episode2.inlineSubtitle = subtitle
            episode2.previewAvailable = false

            context.insert(series)
            context.insert(episode1)
            context.insert(episode2)
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
        let audioURL: URL
        let subtitleURL: URL
        let durationSec: Double
    }

    /// Same real lab assets (and env overrides) as the podcast playable preview
    /// — the auth flow gates the *same kind* of content the playback probe
    /// plays, so the data must be equally real.
    private static func resolveAuthPodcastFixture() throws -> AuthPodcastFixture {
        let env = ProcessInfo.processInfo.environment
        let audioPath = env["KG_UI_TEST_PODCAST_AUDIO"]
            ?? "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/scripts/ep_1_flash.m4a"
        let subtitlePath = env["KG_UI_TEST_PODCAST_SUBTITLE"]
            ?? "/Users/chenliangyu/project/kg/lab/podcast/workspaces/atomic_habits_an_easy_proven_w_033e3990/scripts/ep_1_flash.srt"
        let durationSec = env["KG_UI_TEST_PODCAST_DURATION"].flatMap(Double.init) ?? 1_034.6
        let audioURL = URL(fileURLWithPath: audioPath)
        let subtitleURL = URL(fileURLWithPath: subtitlePath)
        guard FileManager.default.fileExists(atPath: audioURL.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: audioURL.path])
        }
        guard FileManager.default.fileExists(atPath: subtitleURL.path) else {
            throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: subtitleURL.path])
        }
        return AuthPodcastFixture(audioURL: audioURL, subtitleURL: subtitleURL, durationSec: durationSec)
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
