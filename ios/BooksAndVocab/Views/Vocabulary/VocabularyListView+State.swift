//
//  VocabularyListView+State.swift
//  Books & Vocab
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
        allEntries.filter(\.shouldAppearInKnowledgeList)
    }

    // MARK: - Content

    @ViewBuilder
    func contentView() -> some View {
        if !authManager.isLoggedIn {
            loggedOutState
        } else {
            // Why: 詳情頁不再渲染獨立的 VocabReviewBanner — `538 張到期` text +
            // 下方 chip bar `Due 538` 重複；CTA 收進 KGVocabPresenter chip+sort
            // 列尾端的 VocabReviewCTAPill (注入 `onStartReview` callback 觸發)。
            // NotebookListView 走 page section header + VocabReviewCTAPill (D4 editorial)。
            KGVocabView(
                searchText: $debouncedSearchText,
                notebookId: notebookId,
                onEntrySelected: { entry in
                    detailRouter?.showWordDetail(entry, allEntries: allEntries)
                },
                onStartReview: { entries in
                    coordinator.startKnowledgeReview(entries: entries)
                }
            )
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
