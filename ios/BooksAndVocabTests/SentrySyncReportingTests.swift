import Foundation
import Testing
@testable import BooksAndVocab

/// Which background-sync failures are forwarded to Sentry. Offline,
/// network, cancellation and auth-expiry conditions are user-recoverable
/// noise; server, decoding and unexpected failures are actionable.
struct SentrySyncReportingTests {
    @Test func networkCancellationAndAuthFailuresAreNotRecorded() {
        #expect(!KGService.shouldRecordSyncFailure(KGError.networkError(underlying: URLError(.timedOut))))
        #expect(!KGService.shouldRecordSyncFailure(KGError.offline))
        #expect(!KGService.shouldRecordSyncFailure(KGError.unauthorized))
        #expect(!KGService.shouldRecordSyncFailure(KGError.notAuthenticated))
        #expect(!KGService.shouldRecordSyncFailure(CancellationError()))
        #expect(!KGService.shouldRecordSyncFailure(URLError(.cancelled)))
        #expect(!KGService.shouldRecordSyncFailure(URLError(.notConnectedToInternet)))
    }

    @Test func serverAndDecodingFailuresAreRecorded() {
        #expect(KGService.shouldRecordSyncFailure(KGError.httpError(statusCode: 500, detail: "boom")))
        #expect(KGService.shouldRecordSyncFailure(KGError.serverError("boom")))
        #expect(KGService.shouldRecordSyncFailure(
            KGError.decodingError(underlying: DecodingError.dataCorrupted(
                .init(codingPath: [], debugDescription: "bad")
            ))
        ))
        #expect(KGService.shouldRecordSyncFailure(URLError(.badServerResponse)))
    }
}
