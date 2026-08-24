import Foundation

/// Client-side wire contract for the composite Add Link operation.
///
/// The server owns translation, card creation, enrichment, and graph mutation.
/// iOS submits one idempotent command and observes its durable projection.
struct KGAddLinkOperationRequest: Encodable, Equatable {
    let fromId: String
    let targetWord: String
    let translation: String?
    /// Source context is a private sense clue, never the target card's example.
    let context: String
    let source: KGVocabSource?
    let sourceLang: String?
    let targetLang: String?

    private enum CodingKeys: String, CodingKey {
        case fromId = "from_id"
        case targetWord = "target_word"
        case translation
        case context
        case source
        case sourceLang = "source_lang"
        case targetLang = "target_lang"
    }
}

struct KGAddLinkOperationStep: Decodable, Equatable {
    let id: String
    let status: String
    let current: Int
    let total: Int
    let detailCode: String?
}

struct KGAddLinkOperationStatus: Decodable, Equatable {
    let operationId: String
    let notebookId: String
    let status: String
    let sequence: Int
    let steps: [KGAddLinkOperationStep]
    let targetCardId: String?
    let linkId: String?
    let warnings: [String]
    let errorCode: String?

    var isTerminal: Bool {
        ["succeeded", "succeeded_with_warnings", "failed", "interrupted"].contains(status)
    }

    var completedWithWarnings: Bool {
        status == "succeeded_with_warnings" || !warnings.isEmpty
    }
}

protocol AddLinkOperationServing: AnyObject {
    func startAddLinkOperation(
        request: KGAddLinkOperationRequest,
        notebookId: String,
        idempotencyKey: String
    ) async throws -> KGAddLinkOperationStatus

    func fetchAddLinkOperation(operationId: String) async throws -> KGAddLinkOperationStatus
}
