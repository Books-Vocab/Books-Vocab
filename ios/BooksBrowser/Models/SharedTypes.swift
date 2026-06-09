//
//  SharedTypes.swift
//  Books & Vocab
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
    let hidden: Bool?

    init(id: String, cardId: String, word: String, kind: String,
         label: String, confidence: Double, reason: String, hidden: Bool? = nil) {
        self.id = id; self.cardId = cardId; self.word = word; self.kind = kind
        self.label = label; self.confidence = confidence; self.reason = reason
        self.hidden = hidden
    }

    var isHidden: Bool { hidden ?? false }

    /// True when this is an optimistic placeholder awaiting backend response.
    var isPending: Bool { id.hasPrefix("pending-") }

    /// Helper for optimistic updates (KGCardLinkSummary has let fields).
    func withHidden(_ value: Bool) -> KGCardLinkSummary {
        KGCardLinkSummary(id: id, cardId: cardId, word: word, kind: kind,
                          label: label, confidence: confidence, reason: reason,
                          hidden: value)
    }

    static func pending(id: String, cardId: String, word: String) -> KGCardLinkSummary {
        KGCardLinkSummary(
            id: id, cardId: cardId, word: word,
            kind: "shares_usage", label: "分析中…", confidence: 0, reason: "",
            hidden: false
        )
    }
}

struct KGCard: Codable, Identifiable {
    let id: String
    let content: String
    let meaning: String
    let pos: String?
    let difficulty: Double?
    let difficultyTier: String?
    let note: String?
    let collocations: [String]?
    let examples: [String]
    let mode: String
    let isDeleted: Bool?
    let isArchived: Bool?
    let inflections: [String]?
    let linksByKind: [String: [KGCardLinkSummary]]?
    let notebookId: String?
    let source: KGVocabSource?
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

struct KGNotebook: Codable, Identifiable {
    let id: String
    let name: String
    let color: String?
    let coverPattern: String?
    let sortOrder: Int
    let isDefault: Bool
    let isDeleted: Bool
    let cardCount: Int
    let updatedAt: String?
}
