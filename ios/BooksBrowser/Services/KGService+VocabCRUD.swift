//
//  KGService+VocabCRUD.swift
//  BooksBrowser
//

import Foundation

// MARK: - Models

/// Entry to send to KG server
struct KGVocabEntry: Codable {
    let word: String
    let translation: String
    let context: String
    let root_form: String?
}

// MARK: - Vocabulary CRUD

extension KGService {

    func deleteCard(word: String, notebookId: String) async throws {
        let encoded = word.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? word
        try await authenticatedVoid(
            path: "api/vocab/\(encoded)",
            method: "DELETE",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)]
        )
    }

    func archiveCard(word: String, archived: Bool, notebookId: String) async throws {
        let encoded = word.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? word
        try await authenticatedVoid(
            path: "api/vocab/\(encoded)/archive",
            method: "PATCH",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
            body: try JSONEncoder().encode(["archived": archived])
        )
    }

    func moveCards(words: [String], fromNotebook: String, toNotebook: String) async throws {
        let token = try await currentAuthToken()
        guard var components = URLComponents(url: baseURL.appendingPathComponent("api/vocab/move"), resolvingAgainstBaseURL: false) else {
            throw KGError.serverError("Invalid URL for move")
        }
        components.queryItems = [URLQueryItem(name: "notebook_id", value: fromNotebook)]
        guard let url = components.url else {
            throw KGError.serverError("Invalid URL for move")
        }
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)

        let body: [String: Any] = ["words": words, "to_notebook_id": toNotebook]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to move cards")
        }
    }

    func batchAdd(entries: [VocabularyEntry], notebookId: String = "default") async throws -> KGAddResponse {
        let payload = entries.map { entry in
            KGVocabEntry(
                word: entry.word,
                translation: entry.translation,
                context: entry.context,
                root_form: entry.rootForm
            )
        }
        return try await authenticatedDecode(
            KGAddResponse.self,
            path: "api/vocab",
            method: "POST",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
            body: try JSONEncoder().encode(payload)
        )
    }

    func triggerPipeline(notebookId: String = "default") async throws {
        try await authenticatedVoid(
            path: "api/pipeline",
            method: "POST",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)]
        )
    }
}
