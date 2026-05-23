//
//  KGService+Models.swift
//  BooksBrowser
//
//  Wire models for KG API responses / requests.
//

import Foundation

/// KG server health response
struct KGHealthResponse: Codable {
    let status: String
    let cards: Int
    let links: Int
    let pendingCandidates: Int
    let lastModified: String?
}

/// Vocab add response
struct KGAddResponse: Codable {
    let created: Int
    let skipped: Int
    let duplicates: [String]
    let cardIds: [String: String]
}

struct KGTranslationConfig: Codable {
    let source_lang: String?
    let target_lang: String?
}

/// User config request/response
struct KGUserConfig: Codable {
    let translation: KGTranslationConfig?
}
