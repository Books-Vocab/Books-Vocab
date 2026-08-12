#if DEBUG
import Foundation

/// Deterministic HTTP responses for the canonical Settings lifecycle fixture.
///
/// This is deliberately a transport, not a replacement `BackgroundSyncing`
/// implementation: `SettingsCoordinator` still calls `KGService.backgroundSync`,
/// which executes the ordinary push/pull/review pipeline and writes SwiftData.
final class SettingsSyncFixtureTransport: KGHTTPTransport, @unchecked Sendable {
    private let failureMessage: String
    private let lock = NSLock()
    private var vocabPullCount = 0

    init(summary: SettingsFixtureSeed.SyncSummary) {
        guard summary.lifecycle == .terminalError,
              let message = summary.message, !message.isEmpty,
              summary.attempt == 1,
              summary.dataOutcome == .partial
        else {
            preconditionFailure(
                "settings.\(SettingsFixtureID.syncTerminalErrorRetrySuccess.rawValue) must declare terminalError, message, attempt=1, dataOutcome=partial"
            )
        }
        failureMessage = message
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        let path = request.url?.path ?? ""
        switch path {
        case "/api/vocab":
            let attempt = nextVocabPull()
            return response(
                request,
                statusCode: 200,
                body: attempt == 1 ? Self.partialCards : Self.completeCards
            )
        case "/api/dictionary-cards":
            let attempt = currentVocabPull()
            guard attempt > 1 else {
                let body = (try? JSONSerialization.data(withJSONObject: ["error": failureMessage]))
                    ?? Data("{}".utf8)
                return response(
                    request,
                    statusCode: 429,
                    body: body
                )
            }
            return response(request, statusCode: 200, body: Data("[]".utf8))
        case "/api/vocab/review-events":
            return response(
                request,
                statusCode: 200,
                body: Data(#"{"entries":[],"cursor":null}"#.utf8)
            )
        case "/api/health":
            return response(
                request,
                statusCode: 200,
                body: Data(#"{"status":"ok","cards":2,"links":0,"pendingCandidates":0,"lastModified":null}"#.utf8)
            )
        case "/api/user/quota":
            return response(
                request,
                statusCode: 200,
                body: Data(#"{"fraction":0.0,"reset_seconds":3600}"#.utf8)
            )
        default:
            return response(request, statusCode: 404, body: Data("{}".utf8))
        }
    }

    private func nextVocabPull() -> Int {
        lock.lock()
        defer { lock.unlock() }
        vocabPullCount += 1
        return vocabPullCount
    }

    private func currentVocabPull() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return vocabPullCount
    }

    private func response(
        _ request: URLRequest,
        statusCode: Int,
        body: Data
    ) -> (Data, URLResponse) {
        let url = request.url ?? URL(string: "https://settings-fixture.invalid")!
        let headers = statusCode == 429
            ? ["Content-Type": "application/json", "Retry-After": "0"]
            : ["Content-Type": "application/json"]
        let response = HTTPURLResponse(
            url: url,
            statusCode: statusCode,
            httpVersion: nil,
            headerFields: headers
        )!
        return (body, response)
    }

    private static let partialCards = Data(#"""
        [
        {"id":"settings-residual","content":"residual","meaning":"residual","examples":["residual"],"mode":"recognition","isDeleted":false,"isArchived":false}
        ]
        """#.utf8)

    private static let completeCards = Data(#"""
        [
        {"id":"settings-residual","content":"residual","meaning":"residual","examples":["residual"],"mode":"recognition","isDeleted":false,"isArchived":false},
        {"id":"settings-complete","content":"complete","meaning":"complete","examples":["complete"],"mode":"recognition","isDeleted":false,"isArchived":false}
        ]
        """#.utf8)
}
#endif
