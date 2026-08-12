import Foundation

/// HTTP boundary used by `KGService`.
///
/// Keeping the transport below the service preserves the production request,
/// retry, decoding, and SwiftData pipeline while allowing deterministic tests
/// and UI World fixtures to provide real HTTP responses without a live backend.
protocol KGHTTPTransport: AnyObject {
    func data(for request: URLRequest) async throws -> (Data, URLResponse)
}

final class URLSessionKGHTTPTransport: KGHTTPTransport, @unchecked Sendable {
    private let session: URLSession

    init(session: URLSession) {
        self.session = session
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        try await session.data(for: request)
    }
}
