import SwiftUI

// MARK: - WordDetailGraphLinkRow

struct WordDetailGraphLinkRow: View {
    @Environment(\.vocabSkin) private var vocabSkin
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
    }

    private var hiddenRowContent: some View {
        Text(link.word)
            .font(vocabSkin.typography.rowWord)
            .foregroundStyle(vocabSkin.palette.quaternaryText)
            .opacity(0.5)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, vocabSkin.metrics.linkRowVerticalPadding)
    }

    private var pendingRowContent: some View {
        HStack(alignment: .top, spacing: vocabSkin.metrics.linkRowHorizontalGap) {
            VStack(alignment: .leading, spacing: vocabSkin.metrics.linkDetailGap) {
                Text(link.word)
                    .font(vocabSkin.typography.rowWord)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)

                ShimmerLine()
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, vocabSkin.metrics.linkRowVerticalPadding)
    }

    private func linkRowContent(showsAccessory: Bool) -> some View {
        HStack(alignment: .top, spacing: vocabSkin.metrics.linkRowHorizontalGap) {
            VStack(alignment: .leading, spacing: vocabSkin.metrics.linkDetailGap) {
                Text(link.word)
                    .font(vocabSkin.typography.rowWord)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Text(link.reason)
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .lineSpacing(2)
            }

            if showsAccessory {
                Image(systemName: "arrow.up.right")
                    .font(vocabSkin.typography.iconTiny)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, vocabSkin.metrics.linkRowVerticalPadding)
    }
}

// MARK: - ShimmerLine

private struct ShimmerLine: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @State private var shimmerPhase = false

    var body: some View {
        RoundedRectangle(cornerRadius: 3)
            .fill(vocabSkin.palette.tertiaryText.opacity(shimmerPhase ? 0.18 : 0.08))
            .frame(width: 140, height: 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .animation(AppMotion.breathing, value: shimmerPhase)
            .onAppear { shimmerPhase = true }
    }
}

// MARK: - WordDetailMetadataRow (kept for backward compat, simplified)

struct WordDetailMetadataRow<Content: View>: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    @ViewBuilder let trailing: Content

    init(title: String, @ViewBuilder trailing: () -> Content) {
        self.title = title
        self.trailing = trailing()
    }

    var body: some View {
        HStack {
            Text(title.localized)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.quaternaryText)
            Spacer()
            trailing
        }
    }
}

// MARK: - VocabularySyncBadge

struct VocabularySyncBadge: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let status: Int
    let successTone: Color
    let destructiveTone: Color

    var body: some View {
        Group {
            switch VocabularySyncState(rawValue: status) ?? .pending {
            case .synced:
                Label("已同步".localized, systemImage: "checkmark.circle")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(successTone)
            case .failed:
                Label("同步失敗".localized, systemImage: "exclamationmark.circle")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(destructiveTone)
            case .pending:
                Label("待同步".localized, systemImage: "clock")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
            }
        }
    }
}
