//
//  PodcastDownloadManagerResponseTests.swift
//
//  #2104: a finished download whose response is non-2xx (or an error-body
//  content type) must fail — never be saved as `<remoteId>.mp3` and never set
//  `localAudioPath`. Drives the real `URLSessionDownloadDelegate` callback
//  with a stub task carrying the server response.
//

#if os(iOS)
import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
@Suite("PodcastDownloadManager response validation", .serialized)
struct PodcastDownloadManagerResponseTests {

    @Test func notFoundJSONBodyFailsWithoutSavingAudio() async throws {
        let fixture = try Fixture(taskIdentifier: 910_404)
        let location = try fixture.writeDownloadedBody(#"{"detail":"Not Found"}"#)
        let task = StubDownloadTask(
            identifier: fixture.taskIdentifier,
            response: fixture.response(status: 404, contentType: "application/json")
        )
        fixture.manager.beginTracking(task, remoteId: fixture.remoteId)

        fixture.manager.urlSession(URLSession.shared, downloadTask: task, didFinishDownloadingTo: location)
        await fixture.drainMainActorHops { fixture.manager.failed[fixture.remoteId] != nil }

        #expect(fixture.manager.failed[fixture.remoteId] != nil)
        #expect(fixture.episode.localAudioPath == nil)
        #expect(!fixture.manager.isDownloading(remoteId: fixture.remoteId))
        #expect(!FileManager.default.fileExists(atPath: fixture.finalAudioURL.path))
        #expect(!FileManager.default.fileExists(atPath: fixture.stashURL.path))
    }

    @Test func successStatusWithJSONBodyIsRejected() async throws {
        let fixture = try Fixture(taskIdentifier: 910_200)
        let location = try fixture.writeDownloadedBody(#"{"error":"upstream"}"#)
        let task = StubDownloadTask(
            identifier: fixture.taskIdentifier,
            response: fixture.response(status: 200, contentType: "application/json; charset=utf-8")
        )
        fixture.manager.beginTracking(task, remoteId: fixture.remoteId)

        fixture.manager.urlSession(URLSession.shared, downloadTask: task, didFinishDownloadingTo: location)
        await fixture.drainMainActorHops { fixture.manager.failed[fixture.remoteId] != nil }

        #expect(fixture.manager.failed[fixture.remoteId] != nil)
        #expect(fixture.episode.localAudioPath == nil)
        #expect(!FileManager.default.fileExists(atPath: fixture.finalAudioURL.path))
    }

    /// Positive control: the same harness must still save a real audio
    /// response, otherwise the rejection tests above could pass vacuously.
    @Test func audioResponseIsSavedAndMarkedDownloaded() async throws {
        let fixture = try Fixture(taskIdentifier: 910_201)
        defer { try? FileManager.default.removeItem(at: fixture.finalAudioURL) }
        let location = try fixture.writeDownloadedBody("ID3-fake-mp3-bytes")
        let task = StubDownloadTask(
            identifier: fixture.taskIdentifier,
            response: fixture.response(status: 200, contentType: "audio/mpeg")
        )
        fixture.manager.beginTracking(task, remoteId: fixture.remoteId)

        fixture.manager.urlSession(URLSession.shared, downloadTask: task, didFinishDownloadingTo: location)
        await fixture.drainMainActorHops { fixture.episode.localAudioPath != nil }

        #expect(fixture.manager.failed[fixture.remoteId] == nil)
        #expect(fixture.episode.localAudioPath == fixture.finalAudioURL.path)
        #expect(FileManager.default.fileExists(atPath: fixture.finalAudioURL.path))
    }

    struct ResponseCase: Sendable, CustomTestStringConvertible {
        let status: Int
        let contentType: String?
        let rejected: Bool
        var testDescription: String { "\(status) \(contentType ?? "<none>") rejected=\(rejected)" }
    }

    @Test(arguments: [
        ResponseCase(status: 401, contentType: "text/html", rejected: true),
        ResponseCase(status: 503, contentType: "text/html", rejected: true),
        ResponseCase(status: 404, contentType: nil, rejected: true),
        ResponseCase(status: 200, contentType: "text/plain", rejected: true),
        ResponseCase(status: 200, contentType: "application/xml", rejected: true),
        ResponseCase(status: 200, contentType: "application/problem+json", rejected: true),
        ResponseCase(status: 200, contentType: "audio/mpeg", rejected: false),
        ResponseCase(status: 206, contentType: "audio/mpeg", rejected: false),
        ResponseCase(status: 200, contentType: "application/octet-stream", rejected: false),
        ResponseCase(status: 200, contentType: nil, rejected: false),
    ])
    func rejectionMatrix(_ responseCase: ResponseCase) throws {
        var headers: [String: String] = [:]
        if let contentType = responseCase.contentType { headers["Content-Type"] = contentType }
        let response = try #require(HTTPURLResponse(
            url: try #require(URL(string: "https://podcast.test/api/podcasts/s/1/audio")),
            statusCode: responseCase.status,
            httpVersion: "HTTP/1.1",
            headerFields: headers
        ))
        let rejection = PodcastDownloadManager.downloadRejection(for: response)
        #expect((rejection != nil) == responseCase.rejected)
    }

    @Test func nonHTTPResponseIsAccepted() {
        #expect(PodcastDownloadManager.downloadRejection(for: nil) == nil)
    }
}

@MainActor
private struct Fixture {
    let manager = PodcastDownloadManager()
    let container: ModelContainer
    let episode: PodcastEpisode
    let remoteId: String
    let taskIdentifier: Int

    init(taskIdentifier: Int) throws {
        self.taskIdentifier = taskIdentifier
        remoteId = "dl-test-\(UUID().uuidString)_ep_01"
        container = try ModelContainer(
            for: PodcastEpisode.self,
            configurations: ModelConfiguration(isStoredInMemoryOnly: true, cloudKitDatabase: .none)
        )
        episode = PodcastEpisode(remoteId: remoteId, episodeNumber: 1, title: "Pilot", durationSec: 42)
        container.mainContext.insert(episode)
        try container.mainContext.save()
        manager.configure(modelContainer: container, podcastEnabled: true)
    }

    /// `commit` files episodes without a series under `unknown/`.
    var finalAudioURL: URL {
        PodcastDownloadManager.downloadsRoot()
            .appendingPathComponent("unknown", isDirectory: true)
            .appendingPathComponent("\(remoteId).mp3")
    }

    var stashURL: URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("podcast-download-\(taskIdentifier).mp3")
    }

    func writeDownloadedBody(_ body: String) throws -> URL {
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("dl-test-location-\(UUID().uuidString).tmp")
        try Data(body.utf8).write(to: url)
        return url
    }

    func response(status: Int, contentType: String) -> HTTPURLResponse {
        HTTPURLResponse(
            url: URL(string: "https://podcast.test/api/podcasts/s/1/audio")!,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": contentType]
        )!
    }

    /// The delegate hops to MainActor via `Task { @MainActor in … }`; yield
    /// (bounded) until that hop has applied its result.
    func drainMainActorHops(until done: () -> Bool) async {
        var remaining = 200
        while !done(), remaining > 0 {
            await Task.yield()
            remaining -= 1
        }
    }
}

/// `URLSessionDownloadTask` stub exposing a canned server response; the
/// manager only reads `taskIdentifier` and `response` from the task.
private final class StubDownloadTask: URLSessionDownloadTask, @unchecked Sendable {
    private let stubIdentifier: Int
    private let stubResponse: URLResponse?

    init(identifier: Int, response: URLResponse?) {
        stubIdentifier = identifier
        stubResponse = response
        super.init()
    }

    override var taskIdentifier: Int { stubIdentifier }
    override var response: URLResponse? { stubResponse }
}
#endif
