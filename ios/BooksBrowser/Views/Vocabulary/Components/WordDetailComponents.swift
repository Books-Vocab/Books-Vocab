import SwiftUI

// MARK: - WordDetailGraphLinkRow

struct WordDetailGraphLinkRow: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let link: KGCardLinkSummary
    let onTap: (() -> Void)?

    var body: some View {
        Group {
            if let onTap {
                Button(action: onTap) {
                    linkRowContent(showsAccessory: true)
                }
                .buttonStyle(.plain)
                .contentShape(Rectangle())
            } else {
                linkRowContent(showsAccessory: false)
            }
        }
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
