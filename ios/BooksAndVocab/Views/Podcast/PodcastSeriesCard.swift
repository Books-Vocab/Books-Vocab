#if os(iOS)
//
//  PodcastSeriesCard.swift
//  Books & Vocab
//

import SwiftUI

// MARK: - Podcast 卡片

struct PodcastSeriesCard: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    let series: PodcastSeries
    var coverHeight: CGFloat = AppBookshelfMetrics.coverHeightCompact

    private var coverColor: Color {
        NotebookPalette.color(for: series.color)
    }

    /// 串流卡副標：`主持人 · N 集`，無主持人時退回純集數。host 可能很長，
    /// caller 已 `lineLimit(1)` + tail 截斷。
    private var metaLine: String {
        let count = L10n.format("%@ 集", "\(series.episodeCount)")
        let hosts = series.hostNames.joined(separator: ", ")
        guard !hosts.isEmpty else { return count }
        return "\(hosts) · \(count)" // i18n-allow: visual separator between localized parts
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.s2) {
            // 封面 — Mochi 北極星二/三：border 退場、resting 走 z0
            coverView
                .overlay(alignment: .topTrailing) {
                    Image(systemName: "waveform")
                        .font(AppFonts.caption2(weight: .bold))
                        .foregroundStyle(appTheme.palette.primaryText)
                        .padding(AppSpacing.s1)
                        .background(.ultraThinMaterial, in: AppRoundedRect(roundness: AppRoundness.pill))
                        .padding(AppSpacing.s2)
                }
                .overlay(alignment: .topLeading) {
                    if series.isFollowed {
                        Image(systemName: "star.fill")
                            .font(AppFonts.caption2(weight: .bold))
                            .foregroundStyle(appTheme.palette.accent)
                            .padding(AppSpacing.s1)
                            .background(.ultraThinMaterial, in: AppRoundedRect(roundness: AppRoundness.pill))
                            .padding(AppSpacing.s2)
                            .accessibilityLabel(L10n.string("已追蹤"))
                    }
                }
                .appElevation(.z0)

            // 元資料
            VStack(alignment: .leading, spacing: AppSpacing.tinyGap) {
                Text(series.title)
                    .font(AppFonts.caption(weight: .medium))
                    .lineLimit(2, reservesSpace: true)
                    .multilineTextAlignment(.leading)
                    .foregroundStyle(appTheme.palette.primaryText)

                // 串流卡 meta：主持人 · 集數（單行截斷，卡高不變）。無主持人退回純集數。
                Text(metaLine)
                    .font(AppFonts.caption2())
                    .foregroundStyle(appTheme.palette.tertiaryText)
                    .lineLimit(1)
                    .truncationMode(.tail)
            }
        }
        .appHoverLift()
        .enableInjection()
    }

    private var coverView: some View {
        NotebookCoverView(
            color: coverColor,
            pattern: series.coverPattern.flatMap { NotebookCoverPattern(rawValue: $0) },
            coverImagePath: series.coverImagePath,
            name: series.title
        )
        .aspectRatio(2/3, contentMode: .fill)
        .frame(height: coverHeight)
        // 2:3 封面，短邊是寬度（210pt 高 → 140pt 寬）→ >70pt 落 card；沿用書封共用
        // token（`coverRoundness` = card），podcast 封面與書封維持同一手感。
        // r 由 10 → 10.5，正是 card=0.15 的校準來源。
        .clipShape(AppRoundedRect(roundness: AppBookshelfMetrics.coverRoundness))
    }
}
#endif
