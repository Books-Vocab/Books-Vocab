//
//  HealthSnapshotTests.swift
//  Books & Vocab Tests
//
//  鎖 health 探活映射：KGHealthResponse.snapshot 只更新連線狀態 + 卡數，
//  絕不涉及時間欄位。這是「健康檢查不得覆寫 lastSyncDate（最後同步時間）」
//  這條 bug 修復的純 seam —— healthCheck 透過 snapshot 套用狀態，
//  故 snapshot 不含時間 ⇒ healthCheck 不可能再倒退同步時間。
//

import Foundation
import SwiftData
import Testing
@testable import BooksAndVocab

private func makeHealth(
    status: String = "ok",
    cards: Int = 0,
    lastModified: String? = nil
) -> KGHealthResponse {
    KGHealthResponse(
        status: status,
        cards: cards,
        links: 0,
        pendingCandidates: 0,
        lastModified: lastModified
    )
}

struct HealthSnapshotTests {

    @Test func snapshotMapsConnectedAndCards() {
        let snap = makeHealth(status: "ok", cards: 636).snapshot
        #expect(snap.isConnected == true)
        #expect(snap.serverCardCount == 636)
    }

    @Test func snapshotNotConnectedWhenStatusNotOk() {
        #expect(makeHealth(status: "degraded").snapshot.isConnected == false)
    }

    /// 核心回歸：即使後端回了 lastModified（8 小時前），snapshot 也只承載
    /// 連線 + 卡數兩個值，沒有任何時間欄位可寫進 lastSyncDate。
    @Test func snapshotIgnoresLastModifiedEntirely() {
        let stale = "2026-06-06T05:00:00Z"
        let a = makeHealth(status: "ok", cards: 636, lastModified: stale).snapshot
        let b = makeHealth(status: "ok", cards: 636, lastModified: nil).snapshot
        // 有無 lastModified 對映射結果完全無差別
        #expect(a == b)
    }
}

// MARK: - #2714 healthCheck must not log out while the keychain token is still loading

@MainActor
private final class PendingTokenAuthSession: AuthSessionProviding {
    let isLoggedIn = true
    let token: String? = nil
}

@MainActor
private final class RecordingInvalidator: SessionInvalidating {
    private(set) var logoutReasons: [String] = []
    func logout(modelContainer: ModelContainer?, reason: String) { logoutReasons.append(reason) }
    func waitForPendingLocalDataCleanup() async {}
}

private final class UnreachableTransport: KGHTTPTransport, @unchecked Sendable {
    func data(for request: URLRequest) async throws -> (Data, URLResponse) {
        throw URLError(.notConnectedToInternet)
    }
}

@MainActor
struct HealthCheckPendingTokenTests {
    /// applyPersistedSession 先設 isLoggedIn=true、keychain token 稍後才到；
    /// 這個空窗內的探活不可被當成 401 而登出使用者。
    @Test func healthCheckWithPendingTokenDoesNotLogOut() async {
        let invalidator = RecordingInvalidator()
        let service = KGService(
            authSession: PendingTokenAuthSession(),
            sessionInvalidator: invalidator,
            transport: UnreachableTransport(),
            connectivityGate: FixedConnectivityGate(isConnected: true)
        )
        await service.healthCheck()
        #expect(invalidator.logoutReasons.isEmpty)
        #expect(service.isConnected == false)
    }
}
