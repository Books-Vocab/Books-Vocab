//
//  KGService+VocabCRUD.swift
//  Books & Vocab
//

import Foundation

// MARK: - Models

/// Origin of a vocabulary entry — mirrors backend `VocabSource`
/// (`kg/api_models/common.py`). `type` is `"book"` or `"web"`;
/// `url` is web-only, `chapter` is book-only. iOS captures originate
/// from the reader, so `type` is always `"book"` and `url` is `nil`.
struct KGVocabSource: Codable, Equatable {
    let type: String          // "book" | "web"
    let title: String?
    let url: String?          // web only
    let chapter: String?      // book only

    static func book(title: String, chapter: String? = nil) -> KGVocabSource {
        KGVocabSource(type: "book", title: title, url: nil, chapter: chapter)
    }
}

/// Entry to send to KG server
struct KGVocabEntry: Codable {
    let word: String
    let translation: String
    let context: String
    let root_form: String?
    let source: KGVocabSource?
    /// BCP-47 source language (e.g. "en"). Optional — only encoded when
    /// `KGFeatureFlags.vocabularyLangPayloadEnabled` is on. Backend currently
    /// has `extra='ignore'` so any value would be silently dropped.
    let source_lang: String?
    /// BCP-47 target language (e.g. "zh-Hant"). See source_lang note.
    let target_lang: String?
}

struct KGBatchDeleteResponse: Codable {
    let deleted: Int
    let deleted_words: [String]
    let not_found: [String]
}

struct KGBatchArchiveResponse: Codable {
    let updated: Int
    let updated_words: [String]
    let not_found: [String]
}

// MARK: - Vocabulary CRUD

extension KGService {

    func deleteCard(word: String, notebookId: String) async throws {
        try await authenticatedVoid(
            path: "api/vocab/\(word)",
            method: "DELETE",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)]
        )
    }

    func batchDeleteCards(words: [String], notebookId: String) async throws -> KGBatchDeleteResponse {
        let body = try JSONEncoder().encode(["words": words])
        return try await authenticatedDecode(
            KGBatchDeleteResponse.self,
            path: "api/vocab/batch-delete",
            method: "POST",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
            body: body
        )
    }

    func archiveCard(word: String, archived: Bool, notebookId: String) async throws {
        try await authenticatedVoid(
            path: "api/vocab/\(word)/archive",
            method: "PATCH",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
            body: try JSONEncoder().encode(["archived": archived])
        )
    }

    func batchArchiveCards(words: [String], archived: Bool, notebookId: String) async throws -> KGBatchArchiveResponse {
        struct BatchArchiveBody: Encodable {
            let words: [String]
            let archived: Bool
        }
        let body = try JSONEncoder().encode(BatchArchiveBody(words: words, archived: archived))
        return try await authenticatedDecode(
            KGBatchArchiveResponse.self,
            path: "api/vocab/batch-archive",
            method: "PATCH",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
            body: body
        )
    }

    /// `batchAdd` 的 VocabularyEntry → 線上 payload 映射。
    ///
    /// 抽成 static 純函式讓測試與 production 共用同一份邏輯（比照
    /// `SyncCoordinator.locallyResolvableDeletes` 的 dead-test 防護範式）。
    /// `langPayloadEnabled` 以參數注入：`KGFeatureFlags` 是 compile-time
    /// 常量，無法在測試中翻轉；production call site 用預設值。
    static func vocabPayload(
        for entries: [VocabularyEntry],
        langPayloadEnabled: Bool = KGFeatureFlags.vocabularyLangPayloadEnabled
    ) -> [KGVocabEntry] {
        entries.map { entry in
            // iOS captures always originate from the reader, so the source
            // is a book. `bookTitle` is filled at capture time by
            // `ReaderVocabularyContext` — only omit `source` when it is
            // genuinely empty (e.g. demo / legacy entries).
            let title = entry.bookTitle.trimmingCharacters(in: .whitespacesAndNewlines)
            let trimmedChapter = entry.chapterTitle?
                .trimmingCharacters(in: .whitespacesAndNewlines)
            let chapter = (trimmedChapter?.isEmpty == false) ? trimmedChapter : nil
            // Feature flag: backend doesn't persist source_lang/target_lang yet,
            // so suppress the fields entirely until KGFeatureFlags flips on.
            // Once enabled, fall back to currentSource/Target when the local
            // row predates Phase 5 (sourceLang == nil).
            let sourceLangPayload: String?
            let targetLangPayload: String?
            if langPayloadEnabled {
                sourceLangPayload = entry.sourceLang ?? TranslationLanguage.currentSource.rawValue
                targetLangPayload = entry.targetLang ?? TranslationLanguage.currentTarget.rawValue
            } else {
                sourceLangPayload = nil
                targetLangPayload = nil
            }
            return KGVocabEntry(
                word: entry.word,
                translation: entry.translation,
                context: entry.context,
                root_form: entry.rootForm,
                source: title.isEmpty ? nil : .book(title: title, chapter: chapter),
                source_lang: sourceLangPayload,
                target_lang: targetLangPayload
            )
        }
    }

    func batchAdd(entries: [VocabularyEntry], notebookId: String = "default") async throws -> KGAddResponse {
        let payload = Self.vocabPayload(for: entries)
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
