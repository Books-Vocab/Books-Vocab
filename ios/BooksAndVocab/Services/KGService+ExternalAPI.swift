//
//  KGService+ExternalAPI.swift
//  Books & Vocab
//
//  JWT-authenticated management calls for the Pro external API surface.
//

import Foundation

/// Public metadata for one external API key. `apiKey` is populated only by the
/// create response; GET/list and DELETE responses intentionally leave it nil.
struct KGExternalAPIKey: Codable, Equatable, Identifiable, Sendable {
    let keyId: String
    let label: String
    let createdAt: String
    let revokedAt: String?
    let apiKey: String?

    var id: String { keyId }
    var isRevoked: Bool { revokedAt != nil }

    /// Drop the one-time plaintext before putting the record into the list state.
    var redacted: Self {
        Self(
            keyId: keyId,
            label: label,
            createdAt: createdAt,
            revokedAt: revokedAt,
            apiKey: nil
        )
    }
}

private struct KGExternalAPIKeyCreateRequest: Encodable {
    let label: String
}

extension KGService {
    func fetchExternalAPIKeys() async throws -> [KGExternalAPIKey] {
        try await authenticatedDecode(
            [KGExternalAPIKey].self,
            path: "api/v1/api-keys"
        )
    }

    func createExternalAPIKey(label: String) async throws -> KGExternalAPIKey {
        let normalizedLabel = label.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedLabel.isEmpty else {
            throw KGError.serverError("API key label cannot be empty")
        }

        let body = try JSONEncoder().encode(
            KGExternalAPIKeyCreateRequest(label: normalizedLabel)
        )

        // Creation is not idempotent: retrying a timed-out POST could create a
        // second credential. The caller can explicitly retry after seeing the
        // failure, so this operation is deliberately single-shot.
        return try await authenticatedDecode(
            KGExternalAPIKey.self,
            path: "api/v1/api-keys",
            method: "POST",
            body: body,
            retryPolicy: .none
        )
    }

    func revokeExternalAPIKey(id: String) async throws -> KGExternalAPIKey {
        let normalizedID = id.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !normalizedID.isEmpty else {
            throw KGError.serverError("API key id cannot be empty")
        }

        // The server generates a hex key id. Keep the path construction explicit
        // and reject an unexpected slash rather than changing endpoint scope.
        guard !normalizedID.contains("/") else {
            throw KGError.serverError("Invalid API key id")
        }

        return try await authenticatedDecode(
            KGExternalAPIKey.self,
            path: "api/v1/api-keys/\(normalizedID)",
            method: "DELETE",
            retryPolicy: .none
        )
    }
}
