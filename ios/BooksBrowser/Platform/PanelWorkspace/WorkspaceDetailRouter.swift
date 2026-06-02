//
//  WorkspaceDetailRouter.swift
//  BooksBrowser
//
//  DetailRouting adapter — 把既有 word-tap / review 入口（遍布 VocabularyListView /
//  KnowledgeGraphView / WordDetailSheet linked card，皆走 \.detailRouter.showWordDetail）
//  在 regular 路由到 2D PanelWorkspace 開欄，零散改 call site。
//
//  stateless forwarder（只持 workspace ref）：selectedEntry/hasDetail 等讀取屬性
//  皆 stub（經 grep 確認無人經 env 讀取它們，僅呼叫 show* write 操作）。
//

import SwiftUI

@Observable @MainActor
final class WorkspaceDetailRouter: DetailRouting {
    private let workspace: PanelWorkspace

    init(workspace: PanelWorkspace) {
        self.workspace = workspace
    }

    // MARK: DetailRouting — write 入口（路由到 workspace）
    func showWordDetail(_ entry: VocabularyEntry, allEntries: [VocabularyEntry]) {
        // after: nil → 截斷既有、word detail 成為當前欄（單欄 replace 語意）。
        workspace.openColumn(.wordDetail(entryID: entry.id), after: nil)
    }

    func showReview(_ session: TodayReviewSession, allEntries: [VocabularyEntry]) {
        workspace.openColumn(.reviewSession(entryIDs: session.entries.map(\.id)), after: nil)
    }

    func dismiss() {
        if let last = workspace.columns.last?.id {
            workspace.closeColumn(last)
        }
    }

    // MARK: DetailRouting — read 屬性 stub（無人經 \.detailRouter env 讀取；workspace 為 SoT）
    var selectedEntry: VocabularyEntry? {
        get { nil }
        set {}
    }
    var activeReviewSession: TodayReviewSession? {
        get { nil }
        set {}
    }
    var contextEntries: [VocabularyEntry] {
        get { [] }
        set {}
    }
    var hasDetail: Bool { !workspace.columns.isEmpty }
}
