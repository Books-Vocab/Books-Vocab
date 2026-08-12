//
//  ReaderPublicationLoaderTests.swift
//  Books & Vocab Tests
//

import Foundation
import ReadiumShared
import Testing
@testable import BooksAndVocab

@MainActor
struct ReaderPublicationLoaderTests {

    @Test func defaultLoadClockCanBeConstructedFromMainActor() {
        let loader = ReaderPublicationLoader(
            readiumService: UnusedReadiumService(),
            downloadManager: ICloudDownloadManager()
        )

        #expect(loader.clock.now <= ContinuousClock().now)
    }
}

@MainActor
private final class UnusedReadiumService: ReadiumServing {
    func openPublication(at _: URL) async throws -> Publication {
        throw CancellationError()
    }

    func importEPUB(
        from _: URL,
        progress _: (@Sendable (Double) -> Void)?
    ) async throws -> (fileName: String, publication: Publication) {
        throw CancellationError()
    }

    func extractMetadata(from _: Publication) -> (title: String, author: String) {
        fatalError("unused test double")
    }

    func extractCover(from _: Publication) async -> Data? {
        fatalError("unused test double")
    }

    func extractUniqueWords(from _: Publication) async -> Set<String> {
        fatalError("unused test double")
    }
}
