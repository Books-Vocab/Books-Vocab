#if os(iOS)
//
//  ExploreDeckCard.swift
//  Books & Vocab
//
//  Explore 目錄卡片 —— Release remote summaries without an installed canonical
//  asset stay procedural; DEBUG UI World loaded fixtures use strict canonical
//  assets for evidence. + official badge + metadata.
//

import SwiftUI

struct ExploreDeckCard: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    let deck: SharedDeck
    var coverHeight: CGFloat = AppBookshelfMetrics.coverHeightCompact
    var assetAccessibilityIdentifier: String? = nil

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
        // Keep the card summary and the rendered cover image as separate
        // accessibility projections. Evidence must not be attached to this
        // children-ignore/navigation button projection.
        .accessibilityElement(children: .contain)
        .accessibilityLabel(accessibilityLabel)
        .accessibilityAddTraits(.isButton)
        .enableInjection()
    }

    private var coverView: some View {
        NotebookCoverView(
            color: coverColor,
            pattern: deck.coverPattern.flatMap { NotebookCoverPattern(rawValue: $0) },
            source: ExploreDeckCoverEvidence.source(for: deck),
            name: deck.title,
            assetAccessibilityIdentifier: assetAccessibilityIdentifier,
            assetAccessibilityLabel: deck.title,
            assetAccessibilityValue: ExploreDeckCoverEvidence.accessibilityValue(for: deck)
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

enum ExploreDeckCoverEvidence {
    static func source(for deck: SharedDeck) -> NotebookCoverSource {
        let hasCanonicalProjection = deck.coverAssetID != nil
            || deck.coverImagePath != nil
            || deck.coverImageSHA256 != nil
            || deck.coverImageByteSize != nil
            || deck.coverImageContentType != nil

        guard hasCanonicalProjection else { return .procedural }
        guard let path = deck.coverImagePath,
              let sha256 = deck.coverImageSHA256,
              let byteSize = deck.coverImageByteSize else {
            return .invalidCanonicalAsset
        }
        let asset = NotebookCoverAsset(path: path, sha256: sha256, byteSize: byteSize)
        guard asset.hasValidMetadata else { return .invalidCanonicalAsset }
        return .canonicalAsset(asset)
    }

    static func accessibilityValue(for deck: SharedDeck) -> String? {
        guard case let .canonicalAsset(asset) = source(for: deck) else { return nil }
        return asset.accessibilityValue
    }
}
#endif
