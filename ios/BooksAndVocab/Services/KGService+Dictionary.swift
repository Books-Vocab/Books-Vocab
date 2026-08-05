import Foundation
import SwiftData

struct DictionaryMaterializeLinkRequest: Encodable, Equatable {
    let sourceCardId: String
    let notebookId: String
    let provider: String
    let entryKey: String
    let senseKey: String
    let exampleKey: String
}

struct DictionarySelectionRequest: Encodable, Equatable {
    let senseKey: String
    let exampleKey: String
}

struct DictionaryReaderVisibilityRequest: Encodable, Equatable {
    let readerHidden: Bool
}

struct DictionaryMaterializeLinkResponse: Decodable {
    let targetCard: KGCard
    let dictionaryCard: KGDictionaryCardProjection?
    let link: KGGraphLink
    let createdCard: Bool
    let createdLink: Bool
    let replayed: Bool
}

struct DictionaryPromotionResponse: Decodable, Equatable {
    let cardId: String
    let cardRole: String
    let promotionState: String
    let alreadyPromoted: Bool
}

struct DictionaryCardProjectionPage: Decodable {
    let cards: [KGDictionaryCardProjection]
    let nextCursor: String?

    enum CodingKeys: String, CodingKey { case cards, items, nextCursor, next_cursor }

    init(from decoder: Decoder) throws {
        if let single = try? decoder.singleValueContainer(),
           let cards = try? single.decode([KGDictionaryCardProjection].self) {
            self.cards = cards
            nextCursor = nil
            return
        }
        let values = try decoder.container(keyedBy: CodingKeys.self)
        cards = try values.decodeIfPresent([KGDictionaryCardProjection].self, forKey: .cards)
            ?? values.decodeIfPresent([KGDictionaryCardProjection].self, forKey: .items) ?? []
        nextCursor = try values.decodeIfPresent(String.self, forKey: .nextCursor)
            ?? values.decodeIfPresent(String.self, forKey: .next_cursor)
    }
}

protocol DictionaryServing: AnyObject {
    func searchDictionary(
        query: String, sourceLanguage: String, targetLanguage: String
    ) async throws -> DictionarySearchResponse
    func fetchDictionaryEntry(
        provider: String, entryKey: String, targetLanguage: String
    ) async throws -> DictionaryEntryResponse
    func fetchDictionaryCard(cardId: String) async throws -> KGDictionaryCardProjection
    func fetchDictionaryCards(
        since: String?, notebookId: String?, cursor: String?
    ) async throws -> DictionaryCardProjectionPage
    func materializeDictionaryLink(
        request: DictionaryMaterializeLinkRequest, idempotencyKey: String
    ) async throws -> DictionaryMaterializeLinkResponse
    func updateDictionarySelection(
        cardId: String, senseKey: String, exampleKey: String
    ) async throws -> KGDictionaryCardProjection
    func promoteDictionaryCard(cardId: String) async throws -> DictionaryPromotionResponse
    func updateReaderVisibility(cardId: String, readerHidden: Bool) async throws -> KGCard
    func flushReaderVisibilityOutbox(container: ModelContainer) async throws
}

extension DictionaryServing {
    func searchDictionary(query: String, sourceLanguage: String, targetLanguage: String) async throws -> DictionarySearchResponse {
        throw KGError.serverError("Dictionary lookup unavailable")
    }
    func fetchDictionaryEntry(provider: String, entryKey: String, targetLanguage: String) async throws -> DictionaryEntryResponse {
        throw KGError.serverError("Dictionary lookup unavailable")
    }
    func fetchDictionaryCard(cardId: String) async throws -> KGDictionaryCardProjection {
        throw KGError.serverError("Dictionary cards unavailable")
    }
    func fetchDictionaryCards(since: String?, notebookId: String?, cursor: String?) async throws -> DictionaryCardProjectionPage {
        throw KGError.serverError("Dictionary cards unavailable")
    }
    func materializeDictionaryLink(request: DictionaryMaterializeLinkRequest, idempotencyKey: String) async throws -> DictionaryMaterializeLinkResponse {
        throw KGError.serverError("Dictionary materialization unavailable")
    }
    func updateDictionarySelection(cardId: String, senseKey: String, exampleKey: String) async throws -> KGDictionaryCardProjection {
        throw KGError.serverError("Dictionary selection unavailable")
    }
    func promoteDictionaryCard(cardId: String) async throws -> DictionaryPromotionResponse {
        throw KGError.serverError("Dictionary promotion unavailable")
    }
    func updateReaderVisibility(cardId: String, readerHidden: Bool) async throws -> KGCard {
        throw KGError.serverError("Reader visibility unavailable")
    }
    func flushReaderVisibilityOutbox(container: ModelContainer) async throws {
        throw KGError.serverError("Reader visibility unavailable")
    }
}

extension KGService {
    func searchDictionary(
        query: String, sourceLanguage: String = "en", targetLanguage: String = "zh-Hant"
    ) async throws -> DictionarySearchResponse {
        try await authenticatedDecode(
            DictionarySearchResponse.self,
            path: "api/dictionary/search",
            queryItems: [
                URLQueryItem(name: "q", value: query),
                URLQueryItem(name: "source_lang", value: sourceLanguage),
                URLQueryItem(name: "target_lang", value: targetLanguage),
            ],
            retryPolicy: .none
        )
    }

    func fetchDictionaryEntry(
        provider: String, entryKey: String, targetLanguage: String = "zh-Hant"
    ) async throws -> DictionaryEntryResponse {
        try await authenticatedDecode(
            DictionaryEntryResponse.self,
            path: "api/dictionary/entries/\(provider)/\(entryKey)",
            queryItems: [URLQueryItem(name: "target_lang", value: targetLanguage)],
            retryPolicy: .none
        )
    }

    func fetchDictionaryCard(cardId: String) async throws -> KGDictionaryCardProjection {
        try await authenticatedDecode(
            KGDictionaryCardProjection.self,
            path: "api/dictionary/cards/\(cardId)"
        )
    }

    func fetchDictionaryCards(
        since: String? = nil, notebookId: String? = nil, cursor: String? = nil
    ) async throws -> DictionaryCardProjectionPage {
        var query: [URLQueryItem] = []
        if let since { query.append(.init(name: "since", value: since)) }
        if let notebookId { query.append(.init(name: "notebook_id", value: notebookId)) }
        if let cursor { query.append(.init(name: "cursor", value: cursor)) }
        let (data, response) = try await authenticatedRequest(
            path: "api/dictionary-cards",
            queryItems: query.isEmpty ? nil : query
        )
        guard (200...299).contains(response.statusCode) else {
            throw KGError.httpError(
                statusCode: response.statusCode,
                detail: String(data: data, encoding: .utf8) ?? "GET api/dictionary-cards failed"
            )
        }
        do {
            let cards = try JSONDecoder().decode([KGDictionaryCardProjection].self, from: data)
            return DictionaryCardProjectionPage(
                cards: cards,
                nextCursor: response.value(forHTTPHeaderField: "X-Next-Cursor")
            )
        } catch {
            throw KGError.decodingError(underlying: error)
        }
    }

    func materializeDictionaryLink(
        request: DictionaryMaterializeLinkRequest, idempotencyKey: String
    ) async throws -> DictionaryMaterializeLinkResponse {
        try await authenticatedDecode(
            DictionaryMaterializeLinkResponse.self,
            path: "api/graph/links/from-dictionary",
            method: "POST",
            body: try JSONEncoder().encode(request),
            headers: ["Idempotency-Key": idempotencyKey],
            retryPolicy: .none
        )
    }

    func updateDictionarySelection(
        cardId: String, senseKey: String, exampleKey: String
    ) async throws -> KGDictionaryCardProjection {
        try await authenticatedDecode(
            KGDictionaryCardProjection.self,
            path: "api/dictionary/cards/\(cardId)/selection",
            method: "PATCH",
            body: try JSONEncoder().encode(DictionarySelectionRequest(senseKey: senseKey, exampleKey: exampleKey))
        )
    }

    func promoteDictionaryCard(cardId: String) async throws -> DictionaryPromotionResponse {
        try await authenticatedDecode(
            DictionaryPromotionResponse.self,
            path: "api/dictionary/cards/\(cardId)/promote",
            method: "POST",
            retryPolicy: .none
        )
    }

    func updateReaderVisibility(cardId: String, readerHidden: Bool) async throws -> KGCard {
        try await authenticatedDecode(
            KGCard.self,
            path: "api/cards/\(cardId)/reader-visibility",
            method: "PATCH",
            body: try JSONEncoder().encode(DictionaryReaderVisibilityRequest(readerHidden: readerHidden)),
            retryPolicy: .none
        )
    }
}

extension DictionaryCardProjectionPage {
    init(cards: [KGDictionaryCardProjection], nextCursor: String?) {
        self.cards = cards
        self.nextCursor = nextCursor
    }
}
