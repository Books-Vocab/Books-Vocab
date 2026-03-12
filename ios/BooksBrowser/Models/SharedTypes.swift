//
//  SharedTypes.swift
//  BooksBrowser
//
//  Created by 陳亮宇 on 2026/2/24.
//

import Foundation

/// 從 JS 或 Readium 傳來的單字選取資訊
struct WordSelection: Equatable {
    let word: String
    let context: String
    let position: CGPoint

    static func == (lhs: WordSelection, rhs: WordSelection) -> Bool {
        lhs.word == rhs.word && lhs.context == rhs.context
    }
}

struct KGCardLinkSummary: Codable, Identifiable, Equatable {
    let id: String
    let cardId: String
    let word: String
    let kind: String
    let label: String
    let confidence: Double
    let reason: String
}

struct KGCard: Codable, Identifiable {
    let id: String
    let content: String
    let meaning: String
    let pos: String?
    let difficulty: Double?
    let difficultyTier: String?
    let note: String?
    let examples: [String]
    let mode: String
    let isDeleted: Bool?
    let isArchived: Bool?
    let pronunciation: String?
    let inflections: [String]?
    let linksByKind: [String: [KGCardLinkSummary]]?
    let updatedAt: String?
    // Review state (from backend)
    let reviewIntervalHours: Double?
    let nextReviewAt: String?
    let lastReviewedAt: String?
    let reviewCount: Int?
    let lapseCount: Int?
    let reviewStreak: Int?
    let lastReviewFeedback: Int?
}
