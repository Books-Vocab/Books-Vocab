import SwiftUI

// MARK: - WordDetailGraphLinkRow

struct WordDetailGraphLinkRow: View {
    let link: KGCardLinkSummary
    let onTap: (() -> Void)?

    var body: some View {
        Group {
            if let onTap {
                Button(action: onTap) {
                    linkRowContent(showsAccessory: true)
                }
                .buttonStyle(.plain)
            } else {
                linkRowContent(showsAccessory: false)
            }
        }
    }

    private func linkRowContent(showsAccessory: Bool) -> some View {
        HStack(alignment: .top, spacing: AppMetrics.spacingSmall) {
            VStack(alignment: .leading, spacing: 3) {
                Text(link.word)
                    .font(.system(size: 15, weight: .semibold, design: .monospaced))
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Text(link.reason)
                    .font(AppFonts.caption())
                    .foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .lineSpacing(2)
            }

            if showsAccessory {
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 10, weight: .thin))
                    .foregroundStyle(.quaternary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, AppMetrics.spacingSmall)
    }
}

// MARK: - WordDetailMetadataRow (kept for backward compat, simplified)

struct WordDetailMetadataRow<Content: View>: View {
    let title: String
    @ViewBuilder let trailing: Content

    init(title: String, @ViewBuilder trailing: () -> Content) {
        self.title = title
        self.trailing = trailing()
    }

    var body: some View {
        HStack {
            Text(title)
                .font(AppFonts.caption())
                .foregroundStyle(.quaternary)
            Spacer()
            trailing
        }
    }
}

// MARK: - VocabularySyncBadge

struct VocabularySyncBadge: View {
    let status: Int
    let successTone: Color
    let destructiveTone: Color

    var body: some View {
        Group {
            switch status {
            case 1:
                Label("已同步", systemImage: "checkmark.circle")
                    .font(AppFonts.caption(weight: .medium))
                    .foregroundStyle(successTone)
            case 2:
                Label("同步失敗", systemImage: "exclamationmark.circle")
                    .font(AppFonts.caption(weight: .medium))
                    .foregroundStyle(destructiveTone)
            default:
                Label("待同步", systemImage: "clock")
                    .font(AppFonts.caption(weight: .medium))
                    .foregroundStyle(.secondary)
            }
        }
    }
}
