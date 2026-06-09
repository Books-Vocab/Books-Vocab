//
//  KGService+Graph.swift
//  Books & Vocab
//

import Foundation

// MARK: - Models

struct KGGraphLink: Codable, Identifiable, Equatable {
    let id: String
    let fromId: String
    let toId: String
    let kind: String
    let confidence: Double
    let reason: String
}

struct KGManualLinkRequest: Codable {
    let fromId: String
    let toId: String

    enum CodingKeys: String, CodingKey {
        case fromId = "from_id"
        case toId = "to_id"
    }
}

// MARK: - Graph Links

extension KGService {

    func pullGraphLinks() async throws -> [KGGraphLink] {
        try await authenticatedDecode([KGGraphLink].self, path: "api/graph/links")
    }

    func createManualLink(fromId: String, toId: String, notebookId: String) async throws -> KGGraphLink {
        let body = try JSONEncoder().encode(KGManualLinkRequest(fromId: fromId, toId: toId))
        return try await authenticatedDecode(
            KGGraphLink.self,
            path: "api/graph/links",
            method: "POST",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
            body: body
        )
    }

    func deleteLink(linkId: String, notebookId: String) async throws {
        try await authenticatedVoid(
            path: "api/graph/links/\(linkId)",
            method: "DELETE",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)]
        )
    }

    func hideLink(linkId: String, notebookId: String) async throws {
        try await authenticatedVoid(
            path: "api/graph/links/\(linkId)/hide",
            method: "PATCH",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)]
        )
    }

    func unhideLink(linkId: String, notebookId: String) async throws {
        try await authenticatedVoid(
            path: "api/graph/links/\(linkId)/unhide",
            method: "PATCH",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)]
        )
    }
}
