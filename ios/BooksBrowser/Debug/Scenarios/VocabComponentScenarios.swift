#if DEBUG && canImport(Playbook)
import Playbook
import SwiftUI

/// Catalog scenarios for the leaf components in `VocabComponents.swift`.
/// All targets are pure stateless `View` structs fed synthetic props.
/// One category per component.
enum VocabComponentScenarios {
    static func register(in playbook: Playbook) {
        // MARK: - Tone Chip
        playbook.addScenarios(of: "Vocab Components · Tone Chip") {
            Scenario("Variants", layout: .compressed) {
                AppThemeContainer {
                    VStack(alignment: .leading, spacing: 16) {
                        VocabToneChip(text: "正式", tone: .blue)
                        VocabToneChip(text: "口語", tone: .green)
                        VocabToneChip(text: "貶義", tone: .red)
                        VocabToneChip(text: "文學", tone: .purple)
                    }
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Long text", layout: .compressed) {
                AppThemeContainer {
                    VocabToneChip(text: "正式而帶有書面語色彩的語氣", tone: .indigo)
                        .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: - Empty State (Content + Card)
        playbook.addScenarios(of: "Vocab Components · Empty State") {
            Scenario("Content — basic", layout: .fill) {
                AppThemeContainer {
                    VocabEmptyStateContent(
                        title: "尚無單字",
                        systemImage: "book.closed",
                        description: "在閱讀時選取詞彙即可加入詞庫。"
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Content — guidance + action", layout: .fill) {
                AppThemeContainer {
                    VocabEmptyStateContent(
                        title: "今天沒有要複習的單字",
                        systemImage: "checkmark.circle",
                        description: "所有到期單字都已複習完成。",
                        guidanceText: "明天再回來繼續累積記憶。",
                        action: AppEmptyStateAction(
                            title: "查看全部單字",
                            systemImage: "list.bullet",
                            handler: {}
                        ),
                        symbolBounce: true
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Card — with action", layout: .fill) {
                AppThemeContainer {
                    VocabEmptyStateCard(
                        title: "詞庫是空的",
                        systemImage: "tray",
                        description: "開始閱讀並選詞，建立你的第一批單字。",
                        action: AppEmptyStateAction(
                            title: "開始閱讀",
                            systemImage: "book",
                            handler: {}
                        )
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Card — no action", layout: .fill) {
                AppThemeContainer {
                    VocabEmptyStateCard(
                        title: "找不到符合的單字",
                        systemImage: "magnifyingglass",
                        description: "試試調整篩選條件或搜尋關鍵字。"
                    )
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }

        // MARK: - Review Progress Bar
        playbook.addScenarios(of: "Vocab Components · Review Progress Bar") {
            Scenario("Ratios", layout: .compressed) {
                AppThemeContainer {
                    VStack(alignment: .trailing, spacing: 24) {
                        VocabReviewProgressBar(progress: VocabReviewProgress(
                            statusLabel: "剛開始", detailLabel: "0 / 12", ratio: 0.0))
                        VocabReviewProgressBar(progress: VocabReviewProgress(
                            statusLabel: "進行中", detailLabel: "4 / 12", ratio: 0.33))
                        VocabReviewProgressBar(progress: VocabReviewProgress(
                            statusLabel: "快完成", detailLabel: "9 / 12", ratio: 0.75))
                        VocabReviewProgressBar(progress: VocabReviewProgress(
                            statusLabel: "完成", detailLabel: "12 / 12", ratio: 1.0))
                    }
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Detail only (no bar)", layout: .compressed) {
                AppThemeContainer {
                    VocabReviewProgressBar(progress: VocabReviewProgress(
                        statusLabel: "暫無進度", detailLabel: "尚未開始複習", ratio: nil))
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
            Scenario("Over 100% (clamped)", layout: .compressed) {
                AppThemeContainer {
                    VocabReviewProgressBar(progress: VocabReviewProgress(
                        statusLabel: "超額", detailLabel: "15 / 12", ratio: 1.5))
                    .padding(24)
                }
                .environmentObject(AppAppearanceStore.preview)
            }
        }
    }
}
#endif
