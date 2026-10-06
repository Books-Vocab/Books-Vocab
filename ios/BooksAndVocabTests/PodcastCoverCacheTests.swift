import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

struct PodcastCoverCacheTests {
    private func validPNG() throws -> Data {
        try #require(Data(base64Encoded: "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="))
    }

    @Test func cover_cache_component_validates_png_response() {
        let png = try! validPNG()
        let response = HTTPURLResponse(
            url: URL(string: "https://example.test/cover.png")!,
            statusCode: 200,
            httpVersion: nil,
            headerFields: ["Content-Type": "image/png"]
        )!

        #expect(PodcastCoverCaching.isValidResponse(data: png, response: response))
        #expect(!PodcastCoverCaching.isValidResponse(data: Data("html".utf8), response: response))
    }

    @Test @MainActor func valid_cache_skips_fetch_and_malformed_cache_repairs_on_next_sync() async throws {
        let schema = Schema([PodcastSeries.self])
        let container = try ModelContainer(
            for: schema,
            configurations: [ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)]
        )
        let context = ModelContext(container)
        let series = PodcastSeries(remoteId: "cache-test", title: "Cache test", hostNames: [])
        series.coverImageURL = "https://example.test/cover.png?v=cache-test"
        let cacheURL = PodcastCoverCaching.cachedCoverURL(
            seriesId: series.remoteId,
            coverImageURL: series.coverImageURL
        )
        defer { try? FileManager.default.removeItem(at: cacheURL) }
        context.insert(series)
        try context.save()

        let valid = try validPNG()
        try PodcastCoverCaching.write(valid, to: cacheURL)
        series.coverImagePath = cacheURL.path
        var fetchCount = 0
        let kgService = KGService()
        await PodcastCoverCaching.cacheCoverIfNeeded(
            seriesId: series.remoteId,
            context: context,
            kgService: kgService,
            baseURL: "https://example.test",
            fetch: { _ in
                fetchCount += 1
                throw URLError(.resourceUnavailable)
            }
        )
        #expect(fetchCount == 0)

        for malformed in [
            Data(),
            Data("<html>error</html>".utf8),
            Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A]),
            Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x01]),
        ] {
            try PodcastCoverCaching.write(malformed, to: cacheURL)
            var attempts = 0
            let fetch: (String) async throws -> (Data, URLResponse) = { _ in
                attempts += 1
                fetchCount += 1
                let responseData = attempts == 1 ? Data("not-a-png".utf8) : valid
                let response = HTTPURLResponse(
                    url: URL(string: "https://example.test/cover.png")!,
                    statusCode: 200,
                    httpVersion: nil,
                    headerFields: ["Content-Type": "image/png"]
                )!
                return (responseData, response)
            }

            await PodcastCoverCaching.cacheCoverIfNeeded(
                seriesId: series.remoteId,
                context: context,
                kgService: kgService,
                baseURL: "https://example.test",
                fetch: fetch
            )
            await PodcastCoverCaching.cacheCoverIfNeeded(
                seriesId: series.remoteId,
                context: context,
                kgService: kgService,
                baseURL: "https://example.test",
                fetch: fetch
            )
            #expect(attempts == 2)
        }

        #expect(fetchCount == 8)
        #expect(try PodcastCoverCaching.read(from: cacheURL) == valid)
        #expect(series.coverImagePath == cacheURL.path)
    }

    @Test func catalog_transport_exposes_injectable_request_boundary() async throws {
        var seenPath: String?
        var seenAuthorization: String?
        let transport = PodcastCatalogTransport(
            request: { request in
                seenPath = request.url?.path
                seenAuthorization = request.value(forHTTPHeaderField: "Authorization")
                return (Data("[]".utf8), HTTPURLResponse(
                    url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
                )!)
            }
        )

        #expect(transport.basePath == "/api/podcasts")
        let data = try await transport.data(
            from: "https://example.test/api/podcasts", bearerToken: "test-token"
        )
        #expect(seenPath == "/api/podcasts")
        #expect(seenAuthorization == "Bearer test-token")
        #expect(data == Data("[]".utf8))
        #expect(try transport.decode([String].self, from: Data("[\"ok\"]".utf8)) == ["ok"])
    }

    @Test func cover_cache_file_lifecycle_is_owned_by_component() throws {
        let root = FileManager.default.temporaryDirectory
            .appendingPathComponent("PodcastCoverCaching-\(UUID().uuidString)", isDirectory: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let path = root.appendingPathComponent("nested/cover.png")
        let bytes = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x02])

        try PodcastCoverCaching.write(bytes, to: path)
        #expect(try PodcastCoverCaching.read(from: path) == bytes)
        try PodcastCoverCaching.remove(at: path)
        #expect(try PodcastCoverCaching.read(from: path) == nil)
    }

    @Test @MainActor func reconciler_handles_tombstone_episode_delete_and_progress_dedup() throws {
        let schema = Schema([PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self])
        let container = try ModelContainer(
            for: schema,
            configurations: [ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)]
        )
        let context = ModelContext(container)
        let live = PodcastSeries(remoteId: "live", title: "Live", hostNames: [])
        let missing = PodcastSeries(remoteId: "missing", title: "Missing", hostNames: [])
        let ep = PodcastEpisode(remoteId: "live_ep_01", episodeNumber: 1, title: "One", durationSec: 10)
        ep.series = live
        let stale = PodcastEpisode(remoteId: "live_ep_99", episodeNumber: 99, title: "Old", durationSec: 10)
        stale.series = live
        let oldProgress = PodcastProgress(episodeRemoteId: ep.remoteId, lastPlayedTime: 1, completed: false)
        oldProgress.updatedAt = Date(timeIntervalSince1970: 1)
        let newProgress = PodcastProgress(episodeRemoteId: ep.remoteId, lastPlayedTime: 9, completed: false)
        newProgress.updatedAt = Date(timeIntervalSince1970: 2)
        context.insert(live)
        context.insert(missing)
        context.insert(ep)
        context.insert(stale)
        context.insert(oldProgress)
        context.insert(newProgress)
        try context.save()

        PodcastCatalogReconciler.reconcile(
            serverSummaries: [PodcastSeriesSummary(
                id: "live", title: "Live", author: nil, hostNames: nil, color: nil,
                coverPattern: nil, coverImageURL: nil, totalDurationSec: nil,
                episodeCount: 1, updatedAt: "now"
            )],
            fetchedDetails: ["live": PodcastSeriesDetail(
                id: "live", title: "Live", author: nil, hostNames: nil, color: nil,
                coverPattern: nil, coverImageURL: nil, totalDurationSec: nil,
                episodes: [PodcastEpisodeDetail(
                    episodeNumber: 1, title: "One", durationSec: 10, audioAvailable: true,
                    subtitleAvailable: false, subtitleContent: nil
                )], createdAt: nil, updatedAt: nil
            )],
            context: context
        )
        try context.save()

        #expect(live.isSoftDeleted == false)
        #expect(missing.isSoftDeleted == true)
        #expect(try context.fetch(FetchDescriptor<PodcastEpisode>()).map(\.remoteId) == [ep.remoteId])
        let progress = try context.fetch(FetchDescriptor<PodcastProgress>())
        #expect(progress.count == 1)
        #expect(progress.first?.lastPlayedTime == 9)
    }

    @Test @MainActor func empty_summary_still_reconciles_fetched_details_and_progress() throws {
        let schema = Schema([PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self])
        let container = try ModelContainer(
            for: schema,
            configurations: [ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)]
        )
        let context = ModelContext(container)
        let series = PodcastSeries(remoteId: "s1", title: "S1", hostNames: [])
        let keep = PodcastEpisode(remoteId: "s1_ep_01", episodeNumber: 1, title: "One", durationSec: 10)
        keep.series = series
        let remove = PodcastEpisode(remoteId: "s1_ep_02", episodeNumber: 2, title: "Two", durationSec: 10)
        remove.series = series
        let orphan = PodcastProgress(episodeRemoteId: "gone_ep_01", lastPlayedTime: 1, completed: false)
        context.insert(series); context.insert(keep); context.insert(remove); context.insert(orphan)
        try context.save()

        PodcastCatalogReconciler.reconcile(
            serverSummaries: [],
            fetchedDetails: ["s1": PodcastSeriesDetail(
                id: "s1", title: "S1", author: nil, hostNames: nil, color: nil,
                coverPattern: nil, coverImageURL: nil, totalDurationSec: nil,
                episodes: [PodcastEpisodeDetail(
                    episodeNumber: 1, title: "One", durationSec: 10, audioAvailable: true,
                    subtitleAvailable: false, subtitleContent: nil
                )], createdAt: nil, updatedAt: nil
            )],
            context: context
        )
        try context.save()
        #expect(try context.fetch(FetchDescriptor<PodcastEpisode>()).map(\.remoteId) == [keep.remoteId])
        #expect(try context.fetch(FetchDescriptor<PodcastProgress>()).isEmpty)
    }
}
