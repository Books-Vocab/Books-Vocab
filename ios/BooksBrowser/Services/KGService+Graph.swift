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
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/graph/links")
        var request = URLRequest(url: url)
        applyAuth(to: &request, token: token)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to fetch graph links, HTTP \(httpResponse.statusCode)")
        }

        return try JSONDecoder().decode([KGGraphLink].self, from: data)
    }
}
