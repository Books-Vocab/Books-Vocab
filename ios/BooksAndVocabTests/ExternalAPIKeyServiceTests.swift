import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

@MainActor
struct ExternalAPIKeyServiceTests {
    @Test func list_decodes_redacted_key_metadata() async throws {
        let transport = RecordingKGHTTPTransport(
            responses: [
                .init(
                    statusCode: 200,
                    body: #"[{"keyId":"abc123","label":"Reader","createdAt":"2026-08-20T04:00:00Z","revokedAt":null}]"#
                )
            ]
        )
        let service = makeService(transport: transport)

        let keys = try await service.fetchExternalAPIKeys()

        #expect(keys.count == 1)
        #expect(keys[0].keyId == "abc123")
        #expect(keys[0].label == "Reader")
        #expect(keys[0].apiKey == nil)
        #expect(transport.requests.count == 1)
        #expect(transport.requests[0].url?.path == "/api/v1/api-keys")
        #expect(transport.requests[0].httpMethod == "GET")
        #expect(transport.requests[0].value(forHTTPHeaderField: "Authorization")?.hasPrefix("Bearer ") == true)
    }

    @Test func create_sends_label_with_jwt_and_does_not_retry_non_idempotent_request() async throws {
        let transport = RecordingKGHTTPTransport(
            responses: [
                .init(statusCode: 500, body: #"{"detail":"temporary"}"#)
            ]
        )
        let service = makeService(transport: transport)

        await #expect(throws: KGError.self) {
            try await service.createExternalAPIKey(label: "Reader automation")
        }

        #expect(transport.requests.count == 1)
        #expect(transport.requests[0].httpMethod == "POST")
        #expect(transport.requests[0].value(forHTTPHeaderField: "Content-Type") == "application/json")
        let body = try #require(transport.requests[0].httpBody)
        let payload = try JSONSerialization.jsonObject(with: body) as? [String: Any]
        #expect(payload?["label"] as? String == "Reader automation")
    }

    @Test func create_keeps_plaintext_only_in_the_creation_response() async throws {
        let transport = RecordingKGHTTPTransport(
            responses: [
                .init(
                    statusCode: 201,
                    body: #"{"keyId":"abc123","label":"Reader","createdAt":"2026-08-20T04:00:00Z","revokedAt":null,"apiKey":"kg_abc123.secret"}"#
                )
            ]
        )
        let service = makeService(transport: transport)

        let created = try await service.createExternalAPIKey(label: "Reader")

        #expect(created.apiKey == "kg_abc123.secret")
        #expect(created.redacted.apiKey == nil)
    }

    @Test func revoke_uses_key_id_path_and_decodes_revoked_metadata() async throws {
        let transport = RecordingKGHTTPTransport(
            responses: [
                .init(
                    statusCode: 200,
                    body: #"{"keyId":"abc123","label":"Reader","createdAt":"2026-08-20T04:00:00Z","revokedAt":"2026-08-20T05:00:00Z"}"#
                )
            ]
        )
        let service = makeService(transport: transport)

        let revoked = try await service.revokeExternalAPIKey(id: "abc123")

        #expect(revoked.keyId == "abc123")
        #expect(revoked.revokedAt != nil)
        #expect(transport.requests[0].url?.path == "/api/v1/api-keys/abc123")
        #expect(transport.requests[0].httpMethod == "DELETE")
    }

    private func makeService(transport: RecordingKGHTTPTransport) -> KGService {
        KGService(
            authSession: FixedExternalAPIAuthSession(),
            sessionInvalidator: NoopExternalAPISessionInvalidator(),
            transport: transport,
            connectivityGate: FixedConnectivityGate(isConnected: true)
        )
    }
}

@MainActor
private final class FixedExternalAPIAuthSession: AuthSessionProviding {
    let isLoggedIn = true
    let token: String? = "header.eyJleHAiOjQxMzg2Njg0MDB9.signature"
}

@MainActor
private final class NoopExternalAPISessionInvalidator: SessionInvalidating {
    func logout(modelContainer: SwiftData.ModelContainer?, reason: String) {}
    func waitForPendingLocalDataCleanup() async {}
}

private final class RecordingKGHTTPTransport: KGHTTPTransport, @unchecked Sendable {
    struct Response {
        let statusCode: Int
        let body: String
        let headers: [String: String]

        init(statusCode: Int, body: String, headers: [String: String] = [:]) {
            self.statusCode = statusCode
            self.body = body
            self.headers = headers
        }
    }

    private let lock = NSLock()
    private var queuedResponses: [Response]
    private(set) var requests: [URLRequest] = []

    init(responses: [Response]) {
        queuedResponses = responses
    }

    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        let response = lock.withLock {
            requests.append(request)
            return queuedResponses.isEmpty
                ? Response(statusCode: 500, body: #"{"detail":"missing test response"}"#)
                : queuedResponses.removeFirst()
        }
        let url = try #require(request.url)
        let httpResponse = try #require(
            HTTPURLResponse(
                url: url,
                statusCode: response.statusCode,
                httpVersion: nil,
                headerFields: response.headers
            )
        )
        return (Data(response.body.utf8), httpResponse)
    }
}
