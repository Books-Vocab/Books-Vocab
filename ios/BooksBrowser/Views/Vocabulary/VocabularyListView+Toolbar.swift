//
//  VocabularyListView+Toolbar.swift
//  BooksBrowser
//

import SwiftUI

struct VocabularyListToolbar: ViewModifier {
    let isLoggedIn: Bool
    let isSyncing: Bool
    let pendingCount: Int
    let knowledgeReviewCount: Int
    let knowledgeDueCount: Int
    let knowledgeUnlearnedCount: Int
    let onSync: () -> Void
    let onStartDueReview: () -> Void
    let onStartUnlearnedReview: () -> Void
    let onStartAllReview: () -> Void
    let onExportCSV: () -> Void
    let onExportJSON: () -> Void
    let onExportAnki: () -> Void
    let hasSyncedEntries: Bool

    func body(content: Content) -> some View {
        content
            .toolbar {
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

                if isLoggedIn && knowledgeReviewCount > 0 {
                    ToolbarItem(placement: .confirmationAction) {
                        Menu {
                            if knowledgeDueCount > 0 {
                                Button {
                                    onStartDueReview()
                                } label: {
                                    Label(
                                        L10n.format("複習到期卡片（%@）", "\(knowledgeDueCount)"),
                                        systemImage: "clock.badge.exclamationmark"
                                    )
                                }
                            }

                            if knowledgeUnlearnedCount > 0 {
                                Button {
                                    onStartUnlearnedReview()
                                } label: {
                                    Label(
                                        L10n.format("學習新卡片（%@）", "\(knowledgeUnlearnedCount)"),
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

                if hasSyncedEntries {
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
