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

    func deleteCard(word: String) async throws {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/vocab/\(word)")
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        applyAuth(to: &request, token: token)

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to delete '\(word)'")
        }
    }

    func archiveCard(word: String, archived: Bool) async throws {
        let token = try await currentAuthToken()
        let encoded = word.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? word
        let url = baseURL.appendingPathComponent("api/vocab/\(encoded)/archive")
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)
        request.httpBody = try JSONEncoder().encode(["archived": archived])

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to archive '\(word)'")
        }
    }

    func batchAdd(entries: [VocabularyEntry], notebookId: String = "default") async throws -> KGAddResponse {
        let token = try await currentAuthToken()
        var components = URLComponents(url: baseURL.appendingPathComponent("api/vocab"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "notebook_id", value: notebookId)]
        var request = URLRequest(url: components.url!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)

        let payload = entries.map { entry in
            KGVocabEntry(
                word: entry.word,
                translation: entry.translation,
                context: entry.context,
                root_form: entry.rootForm
            )
        }

        request.httpBody = try JSONEncoder().encode(payload)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to add vocabulary")
        }

        return try JSONDecoder().decode(KGAddResponse.self, from: data)
    }

    func triggerPipeline(notebookId: String = "default") async throws {
        let token = try await currentAuthToken()
        var components = URLComponents(url: baseURL.appendingPathComponent("api/pipeline"), resolvingAgainstBaseURL: false)!
        components.queryItems = [URLQueryItem(name: "notebook_id", value: notebookId)]
        let url = components.url!
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        applyAuth(to: &request, token: token)

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }

        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Pipeline failed to start (HTTP \(httpResponse.statusCode))")
        }
    }
}
