//
//  KGService+Notebook.swift
//  Books & Vocab
//
//  Notebook CRUD API calls

import Foundation

extension KGService {

    func fetchNotebooks() async throws -> [KGNotebook] {
        try await authenticatedDecode([KGNotebook].self, path: "api/notebooks")
    }

    func createNotebook(name: String, color: String? = nil, coverPattern: String? = nil) async throws -> KGNotebook {
        var body: [String: String] = ["name": name]
        if let color { body["color"] = color }
        if let coverPattern { body["cover_pattern"] = coverPattern }
        return try await authenticatedDecode(
            KGNotebook.self,
            path: "api/notebooks",
            method: "POST",
            body: try JSONEncoder().encode(body)
        )
    }

    func updateNotebook(id: String, name: String? = nil, color: String? = nil, coverPattern: String? = nil) async throws -> KGNotebook {
        var body: [String: String] = [:]
        if let name { body["name"] = name }
        if let color { body["color"] = color }
        // Always send cover_pattern on update — nil maps to "" (clear), non-nil maps to value
        body["cover_pattern"] = coverPattern ?? ""
        return try await authenticatedDecode(
            KGNotebook.self,
            path: "api/notebooks/\(id)",
            method: "PATCH",
            body: try JSONEncoder().encode(body)
        )
    }

    func deleteNotebook(id: String) async throws {
        try await authenticatedVoid(path: "api/notebooks/\(id)", method: "DELETE")
    }
}
