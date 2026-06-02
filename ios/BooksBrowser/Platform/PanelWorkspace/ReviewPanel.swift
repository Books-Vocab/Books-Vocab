//
//  ReviewPanel.swift
//  BooksBrowser
//
//  由 entry-id 快照重建 TodayReviewSession 並掛 today-review。
//  session 建立**一次**(穩定 UUID,避免每 render 重置)——靠外層
//  ForEach(blocks, id: \.id) 的穩定 Block.id 維持本 view 實例延續。
//

import SwiftUI

struct ReviewPanel: View {
    let entryIDs: [UUID]
    let allEntries: [VocabularyEntry]
    let currentUserID: String?
    let onClose: () -> Void

    @State private var session: TodayReviewSession?

    var body: some View {
        Group {
            if let session {
                TodayReviewPhaseView(
                    session: session,
                    allEntries: allEntries,
                    currentUserID: currentUserID,
                    onClose: onClose
                )
            } else {
                Color.clear
            }
        }
        .onAppear {
            if session == nil {
                let resolved = entryIDs.compactMap { id in allEntries.first { $0.id == id } }
                session = TodayReviewSession(entries: resolved)
            }
        }
    }
}
