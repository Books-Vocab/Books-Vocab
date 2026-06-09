//
//  NotebookDetailPresentation.swift
//  Books & Vocab
//
//  NotebookListView 的 detail/review 呈現分支 — 唯一的 today-review
//  呈現入口（見 TodayReviewPhaseView 註解）。
//  單欄收斂後一律走 modal：
//  - word-detail → toastSheet(WordDetailSheet)
//  - today-review → platformFullScreenCover(TodayReviewPhaseView)
//  不再有 inline 可拖拉 panel（safeAreaInset / DraggableDivider 已移除）。
//

import SwiftUI

struct NotebookDetailPresentation: ViewModifier {
    let detailState: DetailRouter
    let allEntries: [VocabularyEntry]
    let currentUserID: String?

    func body(content: Content) -> some View {
        // Phase-1 probe: does THIS modifier value get rebuilt per flip? It is rebuilt
        // only when the shell (NotebookListView) body re-runs — so `presentation.body`
        // firing per flip ⇒ shell re-evaluated; not firing while `state.init` still
        // climbs ⇒ throwaway comes from a path below the cover, not from the shell.
        let _ = PerfLog.review.mark("presentation.body")
        return content
            .toastSheet(item: Binding(
                get: { detailState.selectedEntry },
                set: { if $0 == nil { detailState.dismiss() } }
            )) { entry in
                WordDetailSheet(entry: entry, allEntries: detailState.contextEntries)
                    .appSheet(.large)
            }
            .platformFullScreenCover(item: Binding(
                get: { detailState.activeReviewSession },
                set: { if $0 == nil { detailState.dismiss() } }
            )) { session in
                // Phase-1 probe: the escaping cover content closure. Re-runs ⇒ the
                // presented subtree (→ TodayReviewView.init → throwaway state.init) is
                // rebuilt. Pin its cadence against the fling timeline.
                let _ = PerfLog.review.mark("cover.content", "buildPhaseView")
                TodayReviewPhaseView(
                    session: session,
                    allEntries: detailState.contextEntries.isEmpty ? allEntries : detailState.contextEntries,
                    currentUserID: currentUserID,
                    onClose: { detailState.dismiss() }
                )
                .toastOverlay()
            }
    }
}
