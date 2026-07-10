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
    /// Explore 複製 provenance（backend NotebookResponse camelCase；舊後端無 → nil）。
    /// 純 optional → synthesized Codable 走 decodeIfPresent（present→值 / absent→nil），行為可預測。
    let sourceSharedDeckId: String?
    let sourceVersion: Int?
}

// MARK: - Shared Decks (Explore) wire models
//
// 唯讀 browse 契約。全部 **lenient decode**：身分欄（deckId/title、卡片 id/content/
// meaning）必填，其餘缺欄降級為安全預設；未知欄位由 keyed decode 天然忽略
// （forward-compat，後端加欄不炸舊 app）。DeckCard **零 SRS 欄位** —— 型別層即不可能
// 洩漏 7 個 review 欄位（結構性去洩漏）。

/// 目錄摘要 / 詳情共用的牌組欄位（backend `DeckSummary`）。
struct SharedDeckSummary: Codable, Identifiable {
    let deckId: String
    let title: String
    let color: String?
    let coverPattern: String?
    let authorLabel: String?
    let isOfficial: Bool
    let cardCount: Int
    let downloadCount: Int
    let ratingAvg: Double?
    let ratingCount: Int
    let languagePair: String?
    let category: String?
    let tags: [String]
    let updatedAt: String?

    var id: String { deckId }

    enum CodingKeys: String, CodingKey {
        case deckId, title, color, coverPattern, authorLabel, isOfficial
        case cardCount, downloadCount, ratingAvg, ratingCount
        case languagePair, category, tags, updatedAt
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        deckId = try c.decode(String.self, forKey: .deckId)
        title = try c.decode(String.self, forKey: .title)
        color = try c.decodeIfPresent(String.self, forKey: .color)
        coverPattern = try c.decodeIfPresent(String.self, forKey: .coverPattern)
        authorLabel = try c.decodeIfPresent(String.self, forKey: .authorLabel)
        isOfficial = try c.decodeIfPresent(Bool.self, forKey: .isOfficial) ?? false
        cardCount = try c.decodeIfPresent(Int.self, forKey: .cardCount) ?? 0
        downloadCount = try c.decodeIfPresent(Int.self, forKey: .downloadCount) ?? 0
        ratingAvg = try c.decodeIfPresent(Double.self, forKey: .ratingAvg)
        ratingCount = try c.decodeIfPresent(Int.self, forKey: .ratingCount) ?? 0
        languagePair = try c.decodeIfPresent(String.self, forKey: .languagePair)
        category = try c.decodeIfPresent(String.self, forKey: .category)
        tags = try c.decodeIfPresent([String].self, forKey: .tags) ?? []
        updatedAt = try c.decodeIfPresent(String.self, forKey: .updatedAt)
    }

    // Memberwise init retained for fixtures / tests (custom decoder replaces synthesized).
    init(
        deckId: String, title: String, color: String? = nil, coverPattern: String? = nil,
        authorLabel: String? = nil, isOfficial: Bool = false, cardCount: Int = 0,
        downloadCount: Int = 0, ratingAvg: Double? = nil, ratingCount: Int = 0,
        languagePair: String? = nil, category: String? = nil, tags: [String] = [],
        updatedAt: String? = nil
    ) {
        self.deckId = deckId; self.title = title; self.color = color
        self.coverPattern = coverPattern; self.authorLabel = authorLabel
        self.isOfficial = isOfficial; self.cardCount = cardCount
        self.downloadCount = downloadCount; self.ratingAvg = ratingAvg
        self.ratingCount = ratingCount; self.languagePair = languagePair
        self.category = category; self.tags = tags; self.updatedAt = updatedAt
    }
}

/// 牌組卡片內容平面（backend `DeckCard`）。**零 SRS 欄位** —— 洩漏結構性不可能。
struct SharedDeckCard: Codable, Identifiable {
    let id: String
    let content: String
    let pos: String?
    let meaning: String
    let examples: [String]
    let collocations: [String]
    let note: String?
    let difficulty: Double?
    let mode: String
    let rootForm: String?
    let inflections: [String]

    enum CodingKeys: String, CodingKey {
        case id, content, pos, meaning, examples, collocations
        case note, difficulty, mode, rootForm, inflections
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        id = try c.decode(String.self, forKey: .id)
        content = try c.decode(String.self, forKey: .content)
        meaning = try c.decode(String.self, forKey: .meaning)
        pos = try c.decodeIfPresent(String.self, forKey: .pos)
        examples = try c.decodeIfPresent([String].self, forKey: .examples) ?? []
        collocations = try c.decodeIfPresent([String].self, forKey: .collocations) ?? []
        note = try c.decodeIfPresent(String.self, forKey: .note)
        difficulty = try c.decodeIfPresent(Double.self, forKey: .difficulty)
        mode = try c.decodeIfPresent(String.self, forKey: .mode) ?? ""
        rootForm = try c.decodeIfPresent(String.self, forKey: .rootForm)
        inflections = try c.decodeIfPresent([String].self, forKey: .inflections) ?? []
    }

    init(
        id: String, content: String, meaning: String, pos: String? = nil,
        examples: [String] = [], collocations: [String] = [], note: String? = nil,
        difficulty: Double? = nil, mode: String = "", rootForm: String? = nil,
        inflections: [String] = []
    ) {
        self.id = id; self.content = content; self.meaning = meaning; self.pos = pos
        self.examples = examples; self.collocations = collocations; self.note = note
        self.difficulty = difficulty; self.mode = mode; self.rootForm = rootForm
        self.inflections = inflections
    }
}

/// `GET /api/decks` — keyset cursor 目錄回應。
struct SharedDeckListResponse: Codable {
    let decks: [SharedDeckSummary]
    let nextCursor: String?
}

/// `GET /api/decks/{deckId}` — 詳情（summary 全欄 flat + 首頁 sample cards）。
struct SharedDeckDetail: Codable {
    let summary: SharedDeckSummary
    let sampleCards: [SharedDeckCard]
    let cardsCursor: String?

    enum CodingKeys: String, CodingKey {
        case sampleCards, cardsCursor
    }

    init(from decoder: Decoder) throws {
        // summary 欄位與 sampleCards/cardsCursor 同層（flat）—— 復用 summary lenient 解碼。
        summary = try SharedDeckSummary(from: decoder)
        let c = try decoder.container(keyedBy: CodingKeys.self)
        sampleCards = try c.decodeIfPresent([SharedDeckCard].self, forKey: .sampleCards) ?? []
        cardsCursor = try c.decodeIfPresent(String.self, forKey: .cardsCursor)
    }

    init(summary: SharedDeckSummary, sampleCards: [SharedDeckCard] = [], cardsCursor: String? = nil) {
        self.summary = summary; self.sampleCards = sampleCards; self.cardsCursor = cardsCursor
    }
}

/// `GET /api/decks/{deckId}/cards` — keyset cursor 卡片分頁。
struct SharedDeckCardsResponse: Codable {
    let cards: [SharedDeckCard]
    let nextCursor: String?
}

/// `POST /api/decks/{deckId}/copy` 回應（backend `DeckCopyResponse`，camelCase 直對）。
/// `alreadyCopied == true` = server 依 idempotencyKey 短路回既有 notebook（transport
/// retry / 遺失回應復原），非新複製。lenient decode：`alreadyCopied` 缺欄降級 false。
struct DeckCopyResponse: Codable {
    let notebookId: String
    let notebookName: String
    let deckId: String
    let sourceVersion: Int
    let cardCount: Int
    let alreadyCopied: Bool

    enum CodingKeys: String, CodingKey {
        case notebookId, notebookName, deckId, sourceVersion, cardCount, alreadyCopied
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        notebookId = try c.decode(String.self, forKey: .notebookId)
        notebookName = try c.decode(String.self, forKey: .notebookName)
        deckId = try c.decode(String.self, forKey: .deckId)
        sourceVersion = try c.decodeIfPresent(Int.self, forKey: .sourceVersion) ?? 0
        cardCount = try c.decodeIfPresent(Int.self, forKey: .cardCount) ?? 0
        alreadyCopied = try c.decodeIfPresent(Bool.self, forKey: .alreadyCopied) ?? false
    }

    init(
        notebookId: String, notebookName: String, deckId: String,
        sourceVersion: Int = 0, cardCount: Int = 0, alreadyCopied: Bool = false
    ) {
        self.notebookId = notebookId; self.notebookName = notebookName
        self.deckId = deckId; self.sourceVersion = sourceVersion
        self.cardCount = cardCount; self.alreadyCopied = alreadyCopied
    }
}
