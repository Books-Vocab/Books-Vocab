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

/// health 探活回應映射到 KGService 可觀測狀態的純結果。
///
/// 刻意**不含**任何時間欄位：`lastModified` 是「後端資料最後被寫入的時間」，
/// 與 `lastSyncDate`（裝置最後一次成功同步的時間，由 `backgroundSync` 設定）語意不同。
/// 過去 healthCheck 把 `lastModified` 寫進 `lastSyncDate`，導致「純 pull、未寫入」的
/// 同步後，timer 觸發 health 就把同步時間倒退回後端上次寫入時刻（顯示「N 小時前」）。
struct HealthSnapshot: Equatable {
    let isConnected: Bool
    let serverCardCount: Int
}

extension KGHealthResponse {
    var snapshot: HealthSnapshot {
        HealthSnapshot(isConnected: status == "ok", serverCardCount: cards)
    }
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

/// User config request/response
struct KGUserConfig: Codable {
    let translation: KGTranslationConfig?
}
