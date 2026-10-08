import SwiftUI

// MARK: - WordDetailGraphLinkRow

struct WordDetailGraphLinkRow: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let link: KGCardLinkSummary
    let onTap: (() -> Void)?
    let onDelete: (() -> Void)?
    var onHide: (() -> Void)?
    var onUnhide: (() -> Void)?
    /// Opens the creation detail (status, retry, remove) of a link whose target is
    /// still being created, failed, or finished with warnings (#2133). Nil = the
    /// row is plain status text.
    var onPendingTap: (() -> Void)?

    var body: some View {
        Group {
            if let creationState = link.pendingCreationState {
                pendingCreationRow(creationState)
            } else if link.isPending {
                pendingRowContent
            } else if link.isHidden {
                hiddenRowContent
            } else if let onTap {
                Button(action: onTap) {
                    linkRowContent(showsAccessory: true)
                }
                .buttonStyle(.plain)
                .contentShape(Rectangle())
            } else {
                linkRowContent(showsAccessory: false)
            }
        }
        .contextMenu {
            if !link.isPending {
                if link.isHidden {
                    if let onUnhide {
                        Button {
                            onUnhide()
                        } label: {
                            Label("恢復連結".localized, systemImage: "eye")
                        }
                    }
                } else {
                    if let onHide {
                        Button {
                            onHide()
                        } label: {
                            Label("隱藏連結".localized, systemImage: "eye.slash")
                        }
                    }
                }
                if let onDelete {
                    Button(role: .destructive) {
                        onDelete()
                    } label: {
                        Label("刪除連結".localized, systemImage: "trash")
                    }
                }
            }
        }
        .enableInjection()
    }

    private var hiddenRowContent: some View {
        Text(link.word)
            .font(appSkin.typography.rowWord)
            .foregroundStyle(appSkin.palette.quaternaryText)
            .opacity(0.5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, appSkin.metrics.linkRowVerticalPadding)
    }

    /// A link being created in the background. Creating = shimmer (it will become a
    /// normal row by itself); failed / warning = a visible status icon, so it never
    /// reads as "loading forever". Tapping opens the same detail as on the review card.
    @ViewBuilder
    private func pendingCreationRow(_ state: KGCardLinkSummary.CreationState) -> some View {
        if let onPendingTap {
            Button(action: onPendingTap) {
                pendingCreationContent(state)
            }
            .buttonStyle(.plain)
            .contentShape(Rectangle())
            .accessibilityIdentifier("wordDetail.link.pending.\(state.rawValue)")
        } else {
            pendingCreationContent(state)
        }
    }

    private func pendingCreationContent(_ state: KGCardLinkSummary.CreationState) -> some View {
        HStack(alignment: .top, spacing: appSkin.metrics.linkRowHorizontalGap) {
            VStack(alignment: .leading, spacing: appSkin.metrics.linkDetailGap) {
                Text(link.word)
                    .font(appSkin.typography.rowWord)
                    .foregroundStyle(appSkin.palette.primaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)

                switch state {
                case .creating:
                    ShimmerLine()
                case .failed:
                    Text(L10n.string("todayReview.link.pending.failed"))
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.destructive)
                        .frame(maxWidth: .infinity, alignment: .leading)
                case .warning:
                    Text(L10n.string("addLink.creation.warning.summary"))
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.warning)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }

            switch state {
            case .creating:
                EmptyView()
            case .failed:
                Image(systemName: "exclamationmark.triangle")
                    .font(appSkin.typography.iconTiny)
                    .foregroundStyle(appSkin.palette.destructive)
            case .warning:
                Image(systemName: "exclamationmark.circle")
                    .font(appSkin.typography.iconTiny)
                    .foregroundStyle(appSkin.palette.warning)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, appSkin.metrics.linkRowVerticalPadding)
    }

    private var pendingRowContent: some View {
        HStack(alignment: .top, spacing: appSkin.metrics.linkRowHorizontalGap) {
            VStack(alignment: .leading, spacing: appSkin.metrics.linkDetailGap) {
                Text(link.word)
                    .font(appSkin.typography.rowWord)
                    .foregroundStyle(appSkin.palette.primaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)

                ShimmerLine()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, appSkin.metrics.linkRowVerticalPadding)
    }

    private func linkRowContent(showsAccessory: Bool) -> some View {
        HStack(alignment: .top, spacing: appSkin.metrics.linkRowHorizontalGap) {
            VStack(alignment: .leading, spacing: appSkin.metrics.linkDetailGap) {
                Text(link.word)
                    .font(appSkin.typography.rowWord)
                    .foregroundStyle(appSkin.palette.primaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Text(link.reason)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.tertiaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .lineSpacing(2)
            }

            if showsAccessory {
                Image(systemName: "arrow.up.right")
                    .font(appSkin.typography.iconTiny)
                    .foregroundStyle(appSkin.palette.quaternaryText)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, appSkin.metrics.linkRowVerticalPadding)
    }
}

// MARK: - ShimmerLine

struct ShimmerLine: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @State private var shimmerPhase = false

    var body: some View {
        // 10pt 高的 skeleton bar — 與 `AppSkeletonLine` 同階，走 pill。
        AppRoundedRect(roundness: AppRoundness.pill)
            .fill(appSkin.palette.tertiaryText.opacity(shimmerPhase ? 0.18 : 0.08))
            .frame(width: 140, height: 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .animation(AppMotion.breathing, value: shimmerPhase)
            .onAppear { shimmerPhase = true }
            .enableInjection()
    }
}
