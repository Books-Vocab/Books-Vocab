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

/// Per-user 全局複習時鐘暫停態(對應後端 ReviewClockConfig)。is_paused + paused_at
/// 複合,共用 updated_at 驅動跨裝置 LWW。
struct KGReviewClockConfig: Codable {
    let is_paused: Bool
    let paused_at: String?
    let updated_at: Double?
}

/// User config request/response
struct KGUserConfig: Codable {
    let translation: KGTranslationConfig?
    let review_clock: KGReviewClockConfig?
}
