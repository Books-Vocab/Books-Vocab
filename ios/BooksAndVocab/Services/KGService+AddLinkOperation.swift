import Foundation

extension KGService: AddLinkOperationServing {}

extension KGService {
    func startAddLinkOperation(
        request: KGAddLinkOperationRequest,
        notebookId: String,
        idempotencyKey: String
    ) async throws -> KGAddLinkOperationStatus {
        try await authenticatedDecode(
            KGAddLinkOperationStatus.self,
            path: "api/graph/links/ensure-target",
            method: "POST",
            queryItems: [URLQueryItem(name: "notebook_id", value: notebookId)],
            body: try JSONEncoder().encode(request),
            headers: ["Idempotency-Key": idempotencyKey]
        )
    }

    func fetchAddLinkOperation(operationId: String) async throws -> KGAddLinkOperationStatus {
        try await authenticatedDecode(
            KGAddLinkOperationStatus.self,
            path: "api/operations/\(operationId)"
        )
    }
}
