import SwiftUI

/// Variants for `VocabReviewBanner`.
///
/// - `.hero` (default): 完整 card UI with title + stats + CTA, cardBackground +
///   cornerRadius. 用於 NotebookListView (Notebooks list page) 作為 primary
///   entry point — 該頁此 banner 就是用戶看到的主 CTA。
/// - `.compact`: stats + CTA 單行 inline, 無 card background / 無 title。
///   用於 VocabularyListView (notebook detail page) — detail 頁已有 filter chip
///   bar 顯示 due/unlearned/reviewed 數字, 不需要再用大 card 重複。
enum VocabReviewBannerStyle {
    case hero
    case compact
}

struct VocabReviewBanner<FilterContent: View>: View {
    @Environment(\.appSkin) private var skin

    let dueCount: Int
    let unlearnedCount: Int
    let style: VocabReviewBannerStyle
    let onStartDue: () -> Void
    let onStartUnlearned: () -> Void
    let onStartMixed: () -> Void
    @ViewBuilder let filterContent: FilterContent

    init(
        dueCount: Int,
        unlearnedCount: Int,
        style: VocabReviewBannerStyle = .hero,
        onStartDue: @escaping () -> Void,
        onStartUnlearned: @escaping () -> Void,
        onStartMixed: @escaping () -> Void,
        @ViewBuilder filterContent: () -> FilterContent = { EmptyView() }
    ) {
        self.dueCount = dueCount
        self.unlearnedCount = unlearnedCount
        self.style = style
        self.onStartDue = onStartDue
        self.onStartUnlearned = onStartUnlearned
        self.onStartMixed = onStartMixed
        self.filterContent = filterContent()
    }

    private var totalCount: Int { dueCount + unlearnedCount }

    /// When both due and unlearned exist, show mixed as primary.
    /// When only one type exists, go directly to that type.
    private var hasBothTypes: Bool { dueCount > 0 && unlearnedCount > 0 }

    var body: some View {
        HStack(alignment: .center, spacing: skin.spacing.inlineGap) {
            VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                if style == .hero {
                    Text("今日複習".localized)
                        .font(skin.typography.sectionTitle)
                        .foregroundStyle(skin.palette.primaryText)
                        .lineLimit(1)
                }

                statsText
                    .font(skin.typography.caption)
                    .foregroundStyle(skin.palette.secondaryText)
                    .lineLimit(1)
            }

            Spacer(minLength: skin.spacing.microGap)

            filterContent

            reviewButton
        }
        .padding(.horizontal, style == .hero ? skin.spacing.cardPadding : skin.metrics.listRowHorizontalInset)
        .padding(.vertical, style == .hero ? skin.spacing.cardPadding : skin.spacing.inlineGap)
        .background(
            Group {
                if style == .hero {
                    RoundedRectangle(cornerRadius: skin.radii.card)
                        .fill(skin.palette.cardBackground)
                }
            }
        )
    }

    @ViewBuilder
    private var statsText: some View {
        HStack(spacing: AppSpacing.s1) {
            if dueCount > 0 {
                Text(L10n.format("%@ 張到期", "\(dueCount)"))
            }
            if hasBothTypes {
                Text("·")
            }
            if unlearnedCount > 0 {
                Text(L10n.format("%@ 未學習", "\(unlearnedCount)"))
            }
        }
    }

    @ViewBuilder
    private var reviewButton: some View {
        if hasBothTypes {
            // Both types: primary button does mixed, menu offers split
            Menu {
                Button {
                    onStartMixed()
                } label: {
                    Label(
                        L10n.format("全部複習（%@）", "\(totalCount)"),
                        systemImage: "rectangle.stack"
                    )
                }

                Divider()

                Button {
                    onStartDue()
                } label: {
                    Label(
                        L10n.format("到期複習（%@）", "\(dueCount)"),
                        systemImage: "clock.badge"
                    )
                }

                Button {
                    onStartUnlearned()
                } label: {
                    Label(
                        L10n.format("未學複習（%@）", "\(unlearnedCount)"),
                        systemImage: "sparkles"
                    )
                }
            } label: {
                Label(L10n.format("開始複習（%@）", "\(totalCount)"), systemImage: "play.fill")
            }
            .buttonStyle(.appCompactAction(.primary))
        } else if dueCount > 0 {
            Button {
                onStartDue()
            } label: {
                Label("到期複習".localized, systemImage: "clock.badge")
            }
            .buttonStyle(.appCompactAction(.primary))
        } else {
            Button {
                onStartUnlearned()
            } label: {
                Label("未學複習".localized, systemImage: "sparkles")
            }
            .buttonStyle(.appCompactAction(.primary))
        }
    }
}

#Preview("Hero variant") {
    VStack(spacing: AppSpacing.s4) {
        VocabReviewBanner(
            dueCount: 42,
            unlearnedCount: 12,
            onStartDue: {},
            onStartUnlearned: {},
            onStartMixed: {}
        )

        VocabReviewBanner(
            dueCount: 5,
            unlearnedCount: 0,
            onStartDue: {},
            onStartUnlearned: {},
            onStartMixed: {}
        )

        VocabReviewBanner(
            dueCount: 0,
            unlearnedCount: 3,
            onStartDue: {},
            onStartUnlearned: {},
            onStartMixed: {}
        )
    }
    .padding()
}

#Preview("Compact variant") {
    VStack(spacing: AppSpacing.s2) {
        VocabReviewBanner(
            dueCount: 538,
            unlearnedCount: 0,
            style: .compact,
            onStartDue: {},
            onStartUnlearned: {},
            onStartMixed: {}
        )
        Divider()
        VocabReviewBanner(
            dueCount: 12,
            unlearnedCount: 4,
            style: .compact,
            onStartDue: {},
            onStartUnlearned: {},
            onStartMixed: {}
        )
    }
}
