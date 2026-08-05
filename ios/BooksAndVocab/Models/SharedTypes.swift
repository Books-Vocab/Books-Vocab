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

struct KGCard: Decodable, Identifiable {
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
    // Dictionary-card fields are optional for backward compatibility with
    // legacy `/api/vocab` payloads.
    let cardRole: String?
    let reviewEligible: Bool?
    let readerHidden: Bool?
    let promotionState: String?
    let promotedAt: String?
    let createdAt: String?

    enum CodingKeys: String, CodingKey {
        case id, content, meaning, pos, difficulty, difficultyTier, note, collocations
        case examples, mode, isDeleted, isArchived, inflections, linksByKind, notebookId
        case source, updatedAt, reviewIntervalHours, nextReviewAt, lastReviewedAt
        case reviewCount, lapseCount, reviewStreak, lastReviewFeedback, cardRole
        case reviewEligible, readerHidden, promotionState, promotedAt, createdAt
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decode(String.self, forKey: .id)
        content = try values.decode(String.self, forKey: .content)
        meaning = try values.decodeIfPresent(String.self, forKey: .meaning) ?? ""
        pos = try values.decodeIfPresent(String.self, forKey: .pos)
        difficulty = try values.decodeIfPresent(Double.self, forKey: .difficulty)
        difficultyTier = try values.decodeIfPresent(String.self, forKey: .difficultyTier)
        note = try values.decodeIfPresent(String.self, forKey: .note)
        collocations = try values.decodeIfPresent([String].self, forKey: .collocations)
        examples = try values.decodeIfPresent([String].self, forKey: .examples) ?? []
        mode = try values.decodeIfPresent(String.self, forKey: .mode)
            ?? VocabularyCardMode.recognition.rawValue
        isDeleted = try values.decodeIfPresent(Bool.self, forKey: .isDeleted)
        isArchived = try values.decodeIfPresent(Bool.self, forKey: .isArchived)
        inflections = try values.decodeIfPresent([String].self, forKey: .inflections)
        linksByKind = try values.decodeIfPresent([String: [KGCardLinkSummary]].self, forKey: .linksByKind)
        notebookId = try values.decodeIfPresent(String.self, forKey: .notebookId)
        source = try values.decodeIfPresent(KGVocabSource.self, forKey: .source)
        updatedAt = try values.decodeIfPresent(String.self, forKey: .updatedAt)
        reviewIntervalHours = try values.decodeIfPresent(Double.self, forKey: .reviewIntervalHours)
        nextReviewAt = try values.decodeIfPresent(String.self, forKey: .nextReviewAt)
        lastReviewedAt = try values.decodeIfPresent(String.self, forKey: .lastReviewedAt)
        reviewCount = try values.decodeIfPresent(Int.self, forKey: .reviewCount)
        lapseCount = try values.decodeIfPresent(Int.self, forKey: .lapseCount)
        reviewStreak = try values.decodeIfPresent(Int.self, forKey: .reviewStreak)
        lastReviewFeedback = try values.decodeIfPresent(Int.self, forKey: .lastReviewFeedback)
        cardRole = try values.decodeIfPresent(String.self, forKey: .cardRole)
        reviewEligible = try values.decodeIfPresent(Bool.self, forKey: .reviewEligible)
        readerHidden = try values.decodeIfPresent(Bool.self, forKey: .readerHidden)
        promotionState = try values.decodeIfPresent(String.self, forKey: .promotionState)
        promotedAt = try values.decodeIfPresent(String.self, forKey: .promotedAt)
        createdAt = try values.decodeIfPresent(String.self, forKey: .createdAt)
    }
}

// MARK: - Dictionary cards

struct LexicalExample: Codable, Equatable, Identifiable {
    let id: String
    let text: String

    enum CodingKeys: String, CodingKey { case id, key, text }

    init(id: String, text: String) {
        self.id = id
        self.text = text
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decodeIfPresent(String.self, forKey: .id)
            ?? values.decode(String.self, forKey: .key)
        text = try values.decode(String.self, forKey: .text)
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(id, forKey: .id)
        try values.encode(text, forKey: .text)
    }
}

struct LexicalSense: Codable, Equatable, Identifiable {
    let id: String
    let partOfSpeech: String?
    let definition: String
    let translations: [String]
    let examples: [LexicalExample]
    let synonyms: [String]
    let antonyms: [String]

    enum CodingKeys: String, CodingKey {
        case id, key, partOfSpeech, part_of_speech, definition, translations
        case examples, synonyms, antonyms
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        id = try values.decodeIfPresent(String.self, forKey: .id)
            ?? values.decode(String.self, forKey: .key)
        partOfSpeech = try values.decodeIfPresent(String.self, forKey: .partOfSpeech)
            ?? values.decodeIfPresent(String.self, forKey: .part_of_speech)
        definition = try values.decode(String.self, forKey: .definition)
        translations = try values.decodeIfPresent([String].self, forKey: .translations) ?? []
        examples = try values.decodeIfPresent([LexicalExample].self, forKey: .examples) ?? []
        synonyms = try values.decodeIfPresent([String].self, forKey: .synonyms) ?? []
        antonyms = try values.decodeIfPresent([String].self, forKey: .antonyms) ?? []
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(id, forKey: .id)
        try values.encodeIfPresent(partOfSpeech, forKey: .partOfSpeech)
        try values.encode(definition, forKey: .definition)
        try values.encode(translations, forKey: .translations)
        try values.encode(examples, forKey: .examples)
        try values.encode(synonyms, forKey: .synonyms)
        try values.encode(antonyms, forKey: .antonyms)
    }
}

struct LexicalAttribution: Codable, Equatable {
    let provider: String
    let sourceURL: String
    let licenseName: String
    let licenseURL: String
    let attributionText: String

    enum CodingKeys: String, CodingKey {
        case provider, sourceURL, source_url, licenseName, license_name
        case licenseURL, license_url, attributionText, attribution_text
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        provider = try values.decode(String.self, forKey: .provider)
        sourceURL = try values.decodeIfPresent(String.self, forKey: .sourceURL)
            ?? values.decode(String.self, forKey: .source_url)
        licenseName = try values.decodeIfPresent(String.self, forKey: .licenseName)
            ?? values.decode(String.self, forKey: .license_name)
        licenseURL = try values.decodeIfPresent(String.self, forKey: .licenseURL)
            ?? values.decode(String.self, forKey: .license_url)
        attributionText = try values.decodeIfPresent(String.self, forKey: .attributionText)
            ?? values.decode(String.self, forKey: .attribution_text)
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(provider, forKey: .provider)
        try values.encode(sourceURL, forKey: .sourceURL)
        try values.encode(licenseName, forKey: .licenseName)
        try values.encode(licenseURL, forKey: .licenseURL)
        try values.encode(attributionText, forKey: .attributionText)
    }
}

/// Provider-neutral lexical snapshot returned by KG backend. iOS never
/// decodes a provider's native JSON shape directly.
struct LexicalEntry: Codable, Equatable, Identifiable {
    let provider: String
    let dictionaryId: String
    let entryKey: String
    let schemaVersion: String
    let word: String
    let sourceLanguage: String
    let targetLanguage: String?
    let pronunciations: [String]
    let senses: [LexicalSense]
    let forms: [String]
    let sourceUrl: String
    let licenseName: String
    let licenseUrl: String
    let attributionText: String
    let fetchedAt: String
    let truncated: Bool

    var id: String { "\(provider):\(entryKey)" }

    enum CodingKeys: String, CodingKey {
        case provider, dictionaryId, dictionary_id, entryKey, entry_key
        case schemaVersion, schema_version, word, language, sourceLanguage
        case targetLanguage, pronunciations, senses, forms, attribution
        case sourceUrl, licenseName, licenseUrl, attributionText, fetchedAt
        case fetched_at, truncated
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        provider = try values.decode(String.self, forKey: .provider)
        dictionaryId = try values.decodeIfPresent(String.self, forKey: .dictionaryId)
            ?? values.decode(String.self, forKey: .dictionary_id)
        entryKey = try values.decodeIfPresent(String.self, forKey: .entryKey)
            ?? values.decode(String.self, forKey: .entry_key)
        if let stringVersion = try? values.decode(String.self, forKey: .schemaVersion) {
            schemaVersion = stringVersion
        } else if let stringVersion = try? values.decode(String.self, forKey: .schema_version) {
            schemaVersion = stringVersion
        } else if let intVersion = try? values.decode(Int.self, forKey: .schemaVersion) {
            schemaVersion = String(intVersion)
        } else {
            schemaVersion = "1"
        }
        word = try values.decode(String.self, forKey: .word)
        sourceLanguage = try values.decodeIfPresent(String.self, forKey: .sourceLanguage)
            ?? values.decodeIfPresent(String.self, forKey: .language) ?? "en"
        targetLanguage = try values.decodeIfPresent(String.self, forKey: .targetLanguage)
        pronunciations = try values.decodeIfPresent([String].self, forKey: .pronunciations) ?? []
        senses = try values.decodeIfPresent([LexicalSense].self, forKey: .senses) ?? []
        forms = try values.decodeIfPresent([String].self, forKey: .forms) ?? []
        if let nested = try values.decodeIfPresent(LexicalAttribution.self, forKey: .attribution) {
            sourceUrl = nested.sourceURL
            licenseName = nested.licenseName
            licenseUrl = nested.licenseURL
            attributionText = nested.attributionText
        } else {
            sourceUrl = try values.decode(String.self, forKey: .sourceUrl)
            licenseName = try values.decode(String.self, forKey: .licenseName)
            licenseUrl = try values.decode(String.self, forKey: .licenseUrl)
            attributionText = try values.decode(String.self, forKey: .attributionText)
        }
        fetchedAt = try values.decodeIfPresent(String.self, forKey: .fetchedAt)
            ?? values.decode(String.self, forKey: .fetched_at)
        truncated = try values.decodeIfPresent(Bool.self, forKey: .truncated) ?? false
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(provider, forKey: .provider)
        try values.encode(dictionaryId, forKey: .dictionaryId)
        try values.encode(entryKey, forKey: .entryKey)
        try values.encode(schemaVersion, forKey: .schemaVersion)
        try values.encode(word, forKey: .word)
        try values.encode(sourceLanguage, forKey: .sourceLanguage)
        try values.encodeIfPresent(targetLanguage, forKey: .targetLanguage)
        try values.encode(pronunciations, forKey: .pronunciations)
        try values.encode(senses, forKey: .senses)
        try values.encode(forms, forKey: .forms)
        try values.encode(sourceUrl, forKey: .sourceUrl)
        try values.encode(licenseName, forKey: .licenseName)
        try values.encode(licenseUrl, forKey: .licenseUrl)
        try values.encode(attributionText, forKey: .attributionText)
        try values.encode(fetchedAt, forKey: .fetchedAt)
        try values.encode(truncated, forKey: .truncated)
    }
}

struct DictionarySearchHit: Codable, Equatable, Identifiable {
    let provider: String
    let dictionaryId: String
    let entryKey: String
    let word: String
    let language: String
    let partsOfSpeech: [String]
    let hasExamples: Bool
    let attribution: LexicalAttribution

    var id: String { "\(provider):\(entryKey)" }
}

struct DictionarySearchResponse: Codable, Equatable {
    let hits: [DictionarySearchHit]
    let cacheStatus: String
}

struct DictionaryEntryResponse: Codable, Equatable {
    let entry: LexicalEntry
    let cacheStatus: String
}

struct KGDictionaryCardProjection: Decodable {
    let card: KGCard
    let dictionaryEntry: LexicalEntry
    let selectedSenseKey: String
    let selectedExampleKey: String
    let materializationStatus: String
    let promotionErrorCode: String?
    let promotionRetryable: Bool
    let links: [KGGraphLink]

    enum CodingKeys: String, CodingKey {
        case card, dictionaryEntry, entry, dictionary
        case selectedSenseKey, selectedExampleKey, materializationStatus
        case promotionErrorCode, promotionRetryable, links
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        if let nested = try values.decodeIfPresent(SavedDictionaryPayload.self, forKey: .dictionary) {
            card = try values.decodeIfPresent(KGCard.self, forKey: .card) ?? nested.card
            dictionaryEntry = nested.entry
            selectedSenseKey = nested.selectedSenseKey
            selectedExampleKey = nested.selectedExampleKey
            materializationStatus = nested.materializationStatus
            promotionErrorCode = nested.promotionErrorCode
            promotionRetryable = nested.promotionRetryable ?? false
            links = try values.decodeIfPresent([KGGraphLink].self, forKey: .links) ?? []
            return
        }
        card = try values.decode(KGCard.self, forKey: .card)
        dictionaryEntry = try values.decodeIfPresent(LexicalEntry.self, forKey: .dictionaryEntry)
            ?? values.decode(LexicalEntry.self, forKey: .entry)
        selectedSenseKey = try values.decode(String.self, forKey: .selectedSenseKey)
        selectedExampleKey = try values.decode(String.self, forKey: .selectedExampleKey)
        materializationStatus = try values.decode(String.self, forKey: .materializationStatus)
        promotionErrorCode = try values.decodeIfPresent(String.self, forKey: .promotionErrorCode)
        promotionRetryable = try values.decodeIfPresent(Bool.self, forKey: .promotionRetryable) ?? false
        links = try values.decodeIfPresent([KGGraphLink].self, forKey: .links) ?? []
    }

    private struct SavedDictionaryPayload: Decodable {
        let card: KGCard
        let entry: LexicalEntry
        let selectedSenseKey: String
        let selectedExampleKey: String
        let materializationStatus: String
        let promotionErrorCode: String?
        let promotionRetryable: Bool?
    }
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
