//
//  VocabularyListView+Toolbar.swift
//  Books & Vocab
//

import SwiftUI

struct VocabularyListToolbar: ViewModifier {
    let isLoggedIn: Bool
    let isSyncing: Bool
    let pendingCount: Int
    let onSync: () -> Void
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
