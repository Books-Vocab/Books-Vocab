//
//  KGService+Notebook.swift
//  BooksBrowser
//
//  Notebook CRUD API calls

import Foundation

extension KGService {

    func fetchNotebooks() async throws -> [KGNotebook] {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/notebooks")
        var request = URLRequest(url: url)
        applyAuth(to: &request, token: token)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to fetch notebooks (HTTP \(httpResponse.statusCode))")
        }

        return try JSONDecoder().decode([KGNotebook].self, from: data)
    }

    func createNotebook(name: String, color: String? = nil) async throws -> KGNotebook {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/notebooks")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)

        var body: [String: String] = ["name": name]
        if let color { body["color"] = color }
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard (200...299).contains(httpResponse.statusCode) else {
            throw KGError.serverError("Failed to create notebook (HTTP \(httpResponse.statusCode))")
        }

        return try JSONDecoder().decode(KGNotebook.self, from: data)
    }

    func updateNotebook(id: String, name: String? = nil, color: String? = nil) async throws -> KGNotebook {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/notebooks/\(id)")
        var request = URLRequest(url: url)
        request.httpMethod = "PATCH"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        applyAuth(to: &request, token: token)

        var body: [String: String] = [:]
        if let name { body["name"] = name }
        if let color { body["color"] = color }
        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to update notebook (HTTP \(httpResponse.statusCode))")
        }

        return try JSONDecoder().decode(KGNotebook.self, from: data)
    }

    func deleteNotebook(id: String) async throws {
        let token = try await currentAuthToken()
        let url = baseURL.appendingPathComponent("api/notebooks/\(id)")
        var request = URLRequest(url: url)
        request.httpMethod = "DELETE"
        applyAuth(to: &request, token: token)

        let (_, response) = try await withRetry { try await sharedURLSession.data(for: request) }

        guard let httpResponse = response as? HTTPURLResponse else {
            throw KGError.serverError("Invalid response")
        }
        if httpResponse.statusCode == 401 { throw KGError.unauthorized }
        guard httpResponse.statusCode == 200 else {
            throw KGError.serverError("Failed to delete notebook (HTTP \(httpResponse.statusCode))")
        }
    }
}
