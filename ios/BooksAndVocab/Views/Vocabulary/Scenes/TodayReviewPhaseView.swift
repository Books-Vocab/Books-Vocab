//
//  TodayReviewPhaseView.swift
//  Books & Vocab
//
//  TodayReview 四態包裝層：loading / empty / error / session。
//  對齊 StatsPresenter / NotebookListView 採用的 VocabSceneShell pattern。
//  TodayReviewView 本身負責 session 內容；本檔只處理外層狀態矩陣。
//  唯一的 today-review 呈現入口 — NotebookDetailPresentation 經此 modal 呈現。
//

import SwiftUI

/// TodayReview 的場景狀態。
///
/// - loading：父層仍在計算今日 due（罕見；entries fetch 通常同步）。
/// - empty：今日無待複習卡片，呈現 empty state 提示。
/// - failure：資料拉取失敗（含網路 / SwiftData 異常），提供 retry。
/// - session：已備齊 entries，正常顯示 TodayReviewView。
enum TodayReviewPhase {
    case loading
    case empty
    case failure(retry: () -> Void)
    case session(
        entries: [VocabularyEntry],
        allEntries: [VocabularyEntry],
        currentUserID: String?
    )
}

/// 將 TodayReview 包成統一狀態矩陣（loading / empty / error / success）。
///
/// 唯一的 today-review 呈現入口：`NotebookDetailPresentation` 經 modal 走本 view，
/// 4-state phase matrix 因此真正生效。session 內容委派給 `TodayReviewView`；
/// 空待複習集合落在 `.empty` 分支提供關閉回饋。
struct TodayReviewPhaseView: View {
    @ObserveInjection private var inject
    let phase: TodayReviewPhase
    let onClose: () -> Void

    /// 從一個 `TodayReviewSession` 推導 phase：
    /// entries 為空 → `.empty`（提供關閉回饋）；否則 → `.session`。
    /// SwiftData `@Query` 同步取得 entries，故 `.loading` / `.failure`
    /// 留給未來 robustness 路徑按需以明確 phase 傳入。
    init(
        session: TodayReviewSession,
        allEntries: [VocabularyEntry],
        currentUserID: String?,
        onClose: @escaping () -> Void
    ) {
        if session.entries.isEmpty {
            self.phase = .empty
        } else {
            self.phase = .session(
                entries: session.entries,
                allEntries: allEntries,
                currentUserID: currentUserID
            )
        }
        self.onClose = onClose
    }

    /// 直接以明確 phase 建構（preview / 未來 robustness 路徑）。
    init(phase: TodayReviewPhase, onClose: @escaping () -> Void) {
        self.phase = phase
        self.onClose = onClose
    }

    var body: some View {
        // Phase-1 probe: this view's `.session` branch builds TodayReviewView, whose
        // `init` runs `State(initialValue: TodayReviewState(...))` (eager autoclosure =
        // throwaway construction). `phaseView.body` firing per flip ⇒ the cover content
        // closure rebuilt this view ⇒ `state.init` climb is downstream of that.
        let _ = PerfLog.review.mark("phaseView.body")
        return Group {
            switch phase {
            case .loading:
                VocabSceneShell(phase: .loading(
                    title: "準備今日複習...".localized,
                    systemImage: "rectangle.stack"
                )) {
                    EmptyView()
                }
                .animatePhaseChange(0)

            case .empty:
                VocabSceneShell(phase: .empty(
                    title: "今日沒有待複習的卡片".localized,
                    systemImage: "checkmark.seal",
                    description: "稍後再回來，或先去探索新單字。".localized,
                    action: .init(
                        title: "關閉".localized,
                        systemImage: "xmark",
                        handler: onClose
                    )
                )) {
                    EmptyView()
                }
                .animatePhaseChange(1)

            case .failure(let retry):
                VocabSceneShell(phase: .error(
                    title: "無法載入今日複習".localized,
                    systemImage: "exclamationmark.triangle",
                    retryAction: retry
                )) {
                    EmptyView()
                }
                .animatePhaseChange(2)

            case .session(let entries, let allEntries, let currentUserID):
                TodayReviewView(
                    entries: entries,
                    allEntries: allEntries,
                    currentUserID: currentUserID,
                    onClose: onClose
                )
                .animatePhaseChange(3)
            }
        }
        .enableInjection()
    }
}

// MARK: - Preview

#Preview("TodayReviewPhase / Loading") {
    AppThemeContainer {
        TodayReviewPhaseView(phase: .loading, onClose: {})
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("TodayReviewPhase / Empty") {
    AppThemeContainer {
        TodayReviewPhaseView(phase: .empty, onClose: {})
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("TodayReviewPhase / Error") {
    AppThemeContainer {
        TodayReviewPhaseView(
            phase: .failure(retry: {}),
            onClose: {}
        )
    }
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("TodayReviewPhase / Session") {
    AppThemeContainer {
        TodayReviewPhaseView(
            phase: .session(
                entries: TodayReviewPhasePreviewData.sampleEntries,
                allEntries: TodayReviewPhasePreviewData.sampleEntries,
                currentUserID: "preview-user"
            ),
            onClose: {}
        )
        .modelContainer(for: [VocabularyEntry.self, ReviewRecord.self, Notebook.self], inMemory: true)
    }
    .environmentObject(AppAppearanceStore.preview)
}

private enum TodayReviewPhasePreviewData {
    static let sampleEntries: [VocabularyEntry] = {
        let e1 = VocabularyEntry(
            word: "meticulous",
            translation: "一絲不苟的",
            context: "The editor was meticulous about every detail.",
            explanation: "做事非常細心、注意細節。",
            partOfSpeech: "adj.",
            bookTitle: "Designing Interfaces",
            chapterTitle: "Writing Tone"
        )
        e1.syncState = .synced
        e1.reviewMode = .recognition
        return [e1]
    }()
}
