import SwiftUI

struct WordDetailHeroCard: View {
    let card: CardPresentation
    let tierTone: Color?
    let tierLabel: String?
    let accentTone: Color
    let translationTone: Color

    var body: some View {
        AppCard {
            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                HStack(alignment: .top, spacing: AppMetrics.spacingMedium) {
                    VStack(alignment: .leading, spacing: AppMetrics.spacingSmall) {
                        Text(card.word)
                            .font(AppFonts.hero(weight: .semibold))
                            .foregroundStyle(.primary)
                            .minimumScaleFactor(0.85)

                        if let pron = card.pronunciation, !pron.isEmpty {
                            Text("/\(pron)/")
                                .font(AppFonts.subhead())
                                .foregroundStyle(.secondary)
                        }
                    }

                    Spacer(minLength: 12)

                    if let tierTone, let tierLabel {
                        AppTag(text: tierLabel, tone: tierTone)
                    }
                }

                HStack(spacing: AppMetrics.spacingSmall) {
                    if let pos = card.partOfSpeech {
                        AppTag(text: pos, tone: accentTone)
                    }
                    AppTag(
                        text: card.reviewMode.localizedTitle,
                        tone: translationTone
                    )
                }

                Text(card.translation)
                    .font(AppFonts.h2(weight: .semibold))
                    .foregroundStyle(translationTone)
                    .fixedSize(horizontal: false, vertical: true)
                    .lineSpacing(3)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.clear)
        }
    }
}

struct WordDetailSectionCard<Content: View>: View {
    let title: String
    let systemImage: String
    let tint: Color
    @ViewBuilder let content: Content

    init(
        title: String,
        systemImage: String,
        tint: Color,
        @ViewBuilder content: () -> Content
    ) {
        self.title = title
        self.systemImage = systemImage
        self.tint = tint
        self.content = content()
    }

    var body: some View {
        AppCard {
            VStack(alignment: .leading, spacing: AppMetrics.spacingMedium) {
                Label {
                    Text(title)
                        .font(AppFonts.caption(weight: .semibold))
                } icon: {
                    Image(systemName: systemImage)
                        .font(.system(size: 12, weight: .thin))
                }
                .foregroundStyle(tint)

                content
            }
        }
    }
}

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
            VStack(alignment: .leading, spacing: 4) {
                Text(link.word)
                    .font(AppFonts.subhead(weight: .semibold))
                    .foregroundStyle(.primary)
                    .frame(maxWidth: .infinity, alignment: .leading)

                Text(link.reason)
                    .font(AppFonts.caption())
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .lineSpacing(2)
            }

            if showsAccessory {
                Image(systemName: "arrow.up.right")
                    .font(.system(size: 12, weight: .thin))
                    .foregroundStyle(.tertiary)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, AppMetrics.spacingSmall)
    }
}

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
                .foregroundStyle(.tertiary)
            Spacer()
            trailing
        }
    }
}

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
