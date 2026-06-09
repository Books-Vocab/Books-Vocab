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

    var body: some View {
        Group {
            if link.isPending {
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
    @Environment(\.appSkin) private var appSkin
    @State private var shimmerPhase = false

    var body: some View {
        RoundedRectangle(cornerRadius: AppRadius.xs)
            .fill(appSkin.palette.tertiaryText.opacity(shimmerPhase ? 0.18 : 0.08))
            .frame(width: 140, height: 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .animation(AppMotion.breathing, value: shimmerPhase)
            .onAppear { shimmerPhase = true }
    }
}
