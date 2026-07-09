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
    /// 電腦模式（Catalyst）專用的一鍵刷新（取代無下拉的桌面）；iOS 不渲染。
    var onRefresh: (() -> Void)? = nil
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
                    // 電腦模式 hover tooltip：與相鄰刷新鈕以文字明確區分「管理同步」vs「立即刷新」。
                    .help("同步詞彙".localized)
                }

                #if targetEnvironment(macCatalyst)
                // 可見的桌面式刷新 affordance（Mac 無 pull-to-refresh）。走 ExplicitSync，
                // 與書架 toolbar 鈕 / ⌘R 共用同一資格 gate + toast 回饋。
                ToolbarItem(placement: .cancellationAction) {
                    Button(action: { onRefresh?() }) {
                        VocabToolbarGlyph(systemImage: "arrow.clockwise")
                    }
                    .accessibilityLabel("重新整理".localized)
                    .accessibilityIdentifier("vocab.refreshButton")
                    .help("重新整理".localized)
                }
                #endif

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
