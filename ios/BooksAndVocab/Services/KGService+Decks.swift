//
//  KGService+Decks.swift
//  Books & Vocab
//
//  Explore 共享牌組寫入路徑（copy）。browse（唯讀 mirror）走
//  `SharedDeckCatalogService`；此檔只放需登入 CurrentUser 的寫入端點。
//

import Foundation

extension KGService {

    /// `POST /api/decks/{deckId}/copy` —— 把官方牌組複製進呼叫者的私人 Notebook。
    /// 需登入（走 `authenticatedDecode` 帶 bearer；guest / 過期 token → 401 → unauthorized）。
    /// server 端已有 per-user 鎖 + copy_log 冪等：同 `idempotencyKey` retry 回同一 notebook。
    func copyDeck(
        deckId: String,
        idempotencyKey: String,
        notebookName: String? = nil
    ) async throws -> DeckCopyResponse {
        var body: [String: String] = ["idempotencyKey": idempotencyKey]
        if let notebookName {
            let trimmed = notebookName.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { body["notebookName"] = trimmed }
        }
        return try await authenticatedDecode(
            DeckCopyResponse.self,
            path: "api/decks/\(deckId)/copy",
            method: "POST",
            body: try JSONEncoder().encode(body),
            // Copy is server-side idempotent by idempotencyKey, so a transport
            // retry is safe — but the endpoint mutates (creates a notebook), so
            // keep the request's own retry policy off and let the CALLER retry
            // with the SAME key (SharedDeckCopyController holds a stable key).
            retryPolicy: .none
        )
    }
}
