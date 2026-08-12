import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

struct PodcastCoverCacheTests {
    @Test func cover_cache_component_validates_png_response() {
        let png = Data([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A, 0x01])
        let response = HTTPURLResponse(
            url: URL(string: "https://example.test/cover.png")!,
            statusCode: 200,
            httpVersion: nil,
            headerFields: ["Content-Type": "image/png"]
        )!

        #expect(PodcastCoverCaching.isValidResponse(data: png, response: response))
        #expect(!PodcastCoverCaching.isValidResponse(data: Data("html".utf8), response: response))
    }

    @Test func catalog_transport_exposes_injectable_request_boundary() {
        let transport = PodcastCatalogTransport(
            request: { request in
                #expect(request.url?.path == "/api/podcasts")
                return (Data("[]".utf8), HTTPURLResponse(
                    url: request.url!, statusCode: 200, httpVersion: nil, headerFields: nil
                )!)
            }
        )

        #expect(transport.basePath == "/api/podcasts")
    }

    @Test @MainActor func reconciler_isolated_from_sync_facade() throws {
        let schema = Schema([PodcastSeries.self, PodcastEpisode.self, PodcastProgress.self])
        let container = try ModelContainer(
            for: schema,
            configurations: [ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)]
        )
        let context = ModelContext(container)
        let series = PodcastSeries(remoteId: "s1", title: "S1", hostNames: [])
        context.insert(series)
        try context.save()

        PodcastCatalogReconciler.reconcile(
            serverSummaries: [], fetchedDetails: [:], context: context
        )

        #expect(series.isSoftDeleted == false)
    }
}
