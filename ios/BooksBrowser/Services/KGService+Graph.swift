//
//  KGService+Graph.swift
//  BooksBrowser
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

// MARK: - Graph Links

extension KGService {

    func pullGraphLinks() async throws -> [KGGraphLink] {
        try await authenticatedDecode([KGGraphLink].self, path: "api/graph/links")
    }
}
