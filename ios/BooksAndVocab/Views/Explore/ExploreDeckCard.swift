#if os(iOS)
//
//  ExploreDeckCard.swift
//  Books & Vocab
//
//  Explore 目錄卡片 —— 復用 procedural NotebookCoverView（非 image）+ 官方徽章 +
//  metadata。鏡射 PodcastSeriesCard 的視覺契約（cover z0、無 border、hover lift）。
//

import SwiftUI

struct ExploreDeckCard: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    let deck: SharedDeck
    var coverHeight: CGFloat = AppBookshelfMetrics.coverHeightCompact

    private var coverColor: Color { NotebookPalette.color(for: deck.color) }

    var body: some View {
        VStack(alignment: .leading, spacing: AppSpacing.s2) {
            coverView
                .overlay(alignment: .topLeading) {
                    if deck.isOfficial { officialBadge }
                }
                .appElevation(.z0)
            metadata
        }
        .appHoverLift()
        // 整卡單一 a11y element：title + 官方 + 卡片數 + 下載 + 評分 收成一句。
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityAddTraits(.isButton)
        .enableInjection()
    }

    private var coverView: some View {
        // deck 標題是使用者/策展資料（i18n 覆蓋外）→ 交給 cover 渲染，靠 lineLimit +
        // 截斷做 render-safety；procedural cover 對 emoji/RTL/長字皆穩定。
        NotebookCoverView(
            color: coverColor,
            pattern: deck.coverPattern.flatMap { NotebookCoverPattern(rawValue: $0) },
            coverImagePath: nil,   // Phase 1b-iii procedural only — 無遠端封面圖
            name: deck.title
        )
        .aspectRatio(2/3, contentMode: .fill)
        .frame(height: coverHeight)
        .clipShape(AppRoundedRect(roundness: AppBookshelfMetrics.coverRoundness))
    }

    private var officialBadge: some View {
        Image(systemName: "checkmark.seal.fill")
            .font(AppFonts.caption2(weight: .bold))
            .foregroundStyle(appTheme.palette.accent)
            .padding(AppSpacing.s1)
            .background(.ultraThinMaterial, in: AppRoundedRect(roundness: AppRoundness.pill))
            .padding(AppSpacing.s2)
            .accessibilityHidden(true)   // 已折進整卡 a11y label
    }

    private var metadata: some View {
        VStack(alignment: .leading, spacing: AppSpacing.tinyGap) {
            Text(deck.title)
                .font(AppFonts.caption(weight: .medium))
                .lineLimit(2, reservesSpace: true)
                .multilineTextAlignment(.leading)
                .foregroundStyle(appTheme.palette.primaryText)

            HStack(spacing: AppSpacing.s2) {
                Label(SharedDeckFormat.compactNumber(deck.cardCount), systemImage: "rectangle.stack")
                if deck.downloadCount > 0 {
                    Label(SharedDeckFormat.compactNumber(deck.downloadCount), systemImage: "arrow.down.circle")
                }
                if let rating = deck.ratingAvg, deck.ratingCount > 0 {
                    Label(SharedDeckFormat.rating(rating), systemImage: "star.fill")
                }
            }
            .font(AppFonts.caption2())
            .monospacedDigit()
            .foregroundStyle(appTheme.palette.tertiaryText)
            .lineLimit(1)
            .accessibilityHidden(true)   // 已折進整卡 a11y label
        }
    }

    private var accessibilityLabel: String {
        var parts: [String] = [deck.title]
        if deck.isOfficial { parts.append(L10n.string("explore.deck.a11y.official")) }
        parts.append(SharedDeckFormat.cardCount(deck.cardCount))
        if deck.downloadCount > 0 {
            parts.append(L10n.format("explore.deck.a11y.downloads", SharedDeckFormat.compactNumber(deck.downloadCount)))
        }
        if let rating = deck.ratingAvg, deck.ratingCount > 0 {
            parts.append(L10n.format(
                "explore.deck.a11y.rating",
                SharedDeckFormat.rating(rating),
                SharedDeckFormat.compactNumber(deck.ratingCount)
            ))
        }
        return parts.joined(separator: L10n.string("，"))
    }
}
#endif
