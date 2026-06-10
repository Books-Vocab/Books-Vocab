//
//  NotebookReviewActionBar.swift
//  Books & Vocab
//
//  今日複習動作列 — 從 NotebookListView.body 抽出的 pill cluster。
//  標題 +（三模式 menu / 單模式 button）CTA pill + 篩選 pill + 新增 pill，
//  包進 mutedFill capsule 容器。純展示 + 回呼，無自身狀態；hasReview /
//  hasBothTypes / totalReview 由 due / unlearned 計數就地推導。
//

import SwiftUI

struct NotebookReviewActionBar: View {
    @Environment(\.appSkin) private var skin

    /// 過濾後（active filter 套用）的到期 / 未學計數 — 決定 CTA pill 顯示哪種模式。
    let dueCount: Int
    let unlearnedCount: Int
    /// 未過濾的「整體是否還有可複習項」— 控制標題與 CTA 區塊的進入。
    /// 與 `dueCount`/`unlearnedCount` 分離：filter 排除掉全部時，標題仍顯示但無 pill
    /// （保留抽出前的行為）。
    let hasReviewItems: Bool
    let notebookCount: Int
    let isFiltered: Bool
    let canCreate: Bool

    let onReviewAll: () -> Void
    let onReviewDue: () -> Void
    let onReviewUnlearned: () -> Void
    let onFilter: () -> Void
    let onCreate: () -> Void

    private var hasBothTypes: Bool { dueCount > 0 && unlearnedCount > 0 }
    private var totalReview: Int { dueCount + unlearnedCount }

    var body: some View {
        HStack(spacing: AppSpacing.s2) {
            if hasReviewItems {
                Text("今日複習".localized)
                    .font(skin.typography.sectionTitle)
                    .foregroundStyle(skin.palette.primaryText)
            }

            Spacer(minLength: 8)

            // CTA pill — 三模式 menu / 單模式 button,inline VocabReviewCTAPill 邏輯
            // 以套用統一 NotebookHeaderPillLabel 規格(高度與 tool pill 對齊)。
            if hasReviewItems {
                ctaPill
            }

            if notebookCount >= 2 {
                Button(action: onFilter) {
                    NotebookHeaderPillLabel(
                        fillColor: skin.palette.buttonIdleFill,
                        foregroundColor: isFiltered ? skin.palette.accent : skin.palette.secondaryText
                    ) {
                        Image(systemName: isFiltered
                            ? "line.3.horizontal.decrease.circle.fill"
                            : "line.3.horizontal.decrease.circle")
                    }
                }
                .buttonStyle(.plain)
                .accessibilityLabel("篩選單字本".localized)
            }

            Button(action: onCreate) {
                NotebookHeaderPillLabel(
                    fillColor: skin.palette.buttonIdleFill,
                    foregroundColor: skin.palette.secondaryText
                ) {
                    Image(systemName: "plus")
                }
            }
            .buttonStyle(.plain)
            .disabled(!canCreate)
            .accessibilityIdentifier("notebook.addButton")
            .accessibilityLabel("新增單字本".localized)
        }
        .padding(.horizontal, AppSpacing.s3)
        .padding(.vertical, AppSpacing.s1)
        .background(
            RoundedRectangle(cornerRadius: AppRadius.lg, style: .continuous)
                .fill(skin.palette.mutedFill.opacity(0.5))
        )
        .overlay(
            RoundedRectangle(cornerRadius: AppRadius.lg, style: .continuous)
                .stroke(skin.palette.divider, lineWidth: 1.5)
        )
    }

    @ViewBuilder
    private var ctaPill: some View {
        if hasBothTypes {
            Menu {
                Button(action: onReviewAll) {
                    Label(L10n.format("全部複習（%@）", "\(totalReview)"), systemImage: "rectangle.stack")
                }
                Divider()
                Button(action: onReviewDue) {
                    Label(L10n.format("到期複習（%@）", "\(dueCount)"), systemImage: "clock.badge")
                }
                Button(action: onReviewUnlearned) {
                    Label(L10n.format("未學複習（%@）", "\(unlearnedCount)"), systemImage: "sparkles")
                }
            } label: {
                NotebookHeaderPillLabel(
                    fillColor: skin.palette.brandHero,
                    foregroundColor: AppColors.onBrandHero
                ) {
                    HStack(spacing: AppSpacing.microGap) {
                        Image(systemName: "play.fill")
                        Text("\(totalReview)").monospacedDigit()
                    }
                }
            }
            .accessibilityIdentifier("notebook.reviewCTA")
            .accessibilityLabel(L10n.format("開始複習，共 %@ 張", "\(totalReview)"))
        } else if dueCount > 0 {
            Button(action: onReviewDue) {
                NotebookHeaderPillLabel(
                    fillColor: skin.palette.brandHero,
                    foregroundColor: AppColors.onBrandHero
                ) {
                    HStack(spacing: AppSpacing.microGap) {
                        Image(systemName: "clock.badge")
                        Text("\(dueCount)").monospacedDigit()
                    }
                }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("notebook.reviewCTA")
            .accessibilityLabel(L10n.format("開始到期複習，%@ 張", "\(dueCount)"))
        } else if unlearnedCount > 0 {
            Button(action: onReviewUnlearned) {
                NotebookHeaderPillLabel(
                    fillColor: skin.palette.brandHero,
                    foregroundColor: AppColors.onBrandHero
                ) {
                    HStack(spacing: AppSpacing.microGap) {
                        Image(systemName: "sparkles")
                        Text("\(unlearnedCount)").monospacedDigit()
                    }
                }
            }
            .buttonStyle(.plain)
            .accessibilityIdentifier("notebook.reviewCTA")
            .accessibilityLabel(L10n.format("開始未學複習，%@ 張", "\(unlearnedCount)"))
        }
    }
}
