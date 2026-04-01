//
//  VocabularyListView+Toolbar.swift
//  BooksBrowser
//

import SwiftUI

struct VocabularyListToolbar: ViewModifier {
    let selectedTab: Int
    let isLoggedIn: Bool
    let isSyncing: Bool
    let pendingCount: Int
    let knowledgeReviewCount: Int
    let knowledgeDueCount: Int
    let onSync: () -> Void
    let onStartDueReview: () -> Void
    let onStartUnlearnedReview: () -> Void
    let onStartAllReview: () -> Void
    let onExportCSV: () -> Void
    let onExportJSON: () -> Void
    let onExportAnki: () -> Void
    let hasPendingEntries: Bool
    let knowledgeDueEntriesCount: Int
    let knowledgeUnlearnedEntriesCount: Int

    func body(content: Content) -> some View {
        content
            .toolbar {
                // Sync button
                ToolbarItem(placement: .cancellationAction) {
                    Button(action: onSync) {
                        VocabToolbarGlyph(
                            systemImage: "arrow.triangle.2.circlepath",
                            badge: pendingCount > 0 ? "\(pendingCount)" : nil
                        )
                        .symbolEffect(.pulse, options: .repeating, isActive: isSyncing)
                    }
                    .accessibilityLabel("同步詞彙".localized)
                }

                // Force refresh (知識庫 tab only)
                if selectedTab == 1 && isLoggedIn {
                    if knowledgeReviewCount > 0 {
                        ToolbarItem(placement: .confirmationAction) {
                            Menu {
                                if knowledgeDueEntriesCount > 0 {
                                    Button {
                                        onStartDueReview()
                                    } label: {
                                        Label(
                                            L10n.format("複習到期卡片（%@）", "\(knowledgeDueEntriesCount)"),
                                            systemImage: "clock.badge.exclamationmark"
                                        )
                                    }
                                }

                                if knowledgeUnlearnedEntriesCount > 0 {
                                    Button {
                                        onStartUnlearnedReview()
                                    } label: {
                                        Label(
                                            L10n.format("學習新卡片（%@）", "\(knowledgeUnlearnedEntriesCount)"),
                                            systemImage: "sparkles"
                                        )
                                    }
                                }

                                Divider()

                                Button {
                                    onStartAllReview()
                                } label: {
                                    Label(
                                        L10n.format("全部複習（%@）", "\(knowledgeReviewCount)"),
                                        systemImage: "rectangle.stack"
                                    )
                                }
                            } label: {
                                VocabToolbarGlyph(
                                    systemImage: "rectangle.stack.badge.play",
                                    badge: knowledgeDueCount > 0 ? "\(knowledgeDueCount)" : "\(knowledgeReviewCount)"
                                )
                            }
                        }
                    }

                }

                // Export menu (only for local vocab tab)
                if selectedTab == 0 && hasPendingEntries {
                    ToolbarItem(placement: .confirmationAction) {
                        Menu {
                            Button {
                                onExportCSV()
                            } label: {
                                Label("匯出 CSV".localized, systemImage: "tablecells")
                            }

                            Button {
                                onExportJSON()
                            } label: {
                                Label("匯出 JSON".localized, systemImage: "doc.text")
                            }

                            Button {
                                onExportAnki()
                            } label: {
                                Label("匯出 Anki TSV".localized, systemImage: "rectangle.stack")
                            }
                        } label: {
                            VocabToolbarGlyph(systemImage: "square.and.arrow.up")
                        }
                    }
                }
            }
    }
}
