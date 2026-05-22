//
//  VocabularyListView+State.swift
//  BooksBrowser
//

import SwiftUI

extension VocabularyListView {

    var pendingEntries: [VocabularyEntry] {
        VocabularyEntryPresentation.pendingEntries(in: allEntries)
    }

    var pendingCount: Int {
        pendingEntries.count
    }

    var syncedEntries: [VocabularyEntry] {
        allEntries.filter { $0.syncStatus == 1 && $0.syncAction != .delete && !$0.isArchived }
    }

    // MARK: - Content

    @ViewBuilder
    func contentView(classified: VocabularyEntryPresentation.ClassifiedResult) -> some View {
        if !authManager.isLoggedIn {
            loggedOutState
        } else {
            VStack(spacing: 0) {
                // Why: detail page 已有 filter chip bar 顯示 due/unlearned/reviewed
                // 數字，hero card 與下方 NotebookListView 的 hero CTA 視覺重複。
                // 此處改用 `.compact` 變體 — 無 card background、單行 inline、padding
                // 砍半，省約 60pt 縱向空間，又保留 CTA 入口。NotebookListView 那
                // 邊維持 .hero 變體作為 primary entry point。
                if classified.dueCount > 0 || classified.unlearnedCount > 0 {
                    VocabReviewBanner(
                        dueCount: classified.dueCount,
                        unlearnedCount: classified.unlearnedCount,
                        style: .compact,
                        onStartDue: { coordinator.startKnowledgeReview(entries: classified.dueBucket) },
                        onStartUnlearned: { coordinator.startKnowledgeReview(entries: classified.unlearnedBucket) },
                        onStartMixed: { coordinator.startKnowledgeReview(entries: classified.dueBucket + classified.unlearnedBucket) }
                    )
                }

                KGVocabView(searchText: $debouncedSearchText, notebookId: notebookId) { entry in
                    detailRouter?.showWordDetail(entry, allEntries: allEntries)
                }
            }
        }
    }

    // MARK: - Logged Out

    @ViewBuilder
    var loggedOutState: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                AppEmptyStateCard(
                    title: "需登入帳號".localized,
                    systemImage: "person.crop.circle.badge.exclamationmark",
                    description: "此功能需要登入帳號後才能存取您的雲端資料。".localized
                )

                Button("前往設定登入".localized) {
                    coordinator.presentSettings()
                }
                .buttonStyle(.appAction(.primary))

                Button(action: {
                    authManager.enterDemoMode(modelContainer: modelContext.container)
                }) {
                    HStack(spacing: 6) {
                        Image(systemName: "play.circle")
                        Text("先體驗看看".localized)
                    }
                    .font(AppFonts.body(weight: .medium))
                    .foregroundStyle(appTheme.palette.accent)
                }
                .buttonStyle(.plain)
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppSpacing.s4)
        }
    }
}
