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
        HStack(alignment: .top, spacing: AppMetrics.spacingSmall) {
            VStack(alignment: .leading, spacing: 3) {
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
        .padding(.vertical, AppMetrics.spacingSmall)
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
            switch status {
            case 1:
                Label("已同步", systemImage: "checkmark.circle")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(successTone)
            case 2:
                Label("同步失敗", systemImage: "exclamationmark.circle")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(destructiveTone)
            default:
                Label("待同步", systemImage: "clock")
                    .font(vocabSkin.typography.caption)
                    .foregroundStyle(vocabSkin.palette.secondaryText)
            }
        }
    }
}
