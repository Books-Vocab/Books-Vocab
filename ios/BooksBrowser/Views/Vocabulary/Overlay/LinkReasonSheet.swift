import SwiftUI

struct LinkReasonSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

    let link: KGCardLinkSummary
    let onNavigate: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: "paperclip")
                    .font(vocabSkin.typography.iconSmall)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)

                Text(link.label.localized)
                    .font(vocabSkin.typography.captionStrong)
                    .foregroundStyle(vocabSkin.palette.tertiaryText)
            }

            Text(link.word)
                .font(vocabSkin.typography.detailWord)
                .foregroundStyle(vocabSkin.palette.primaryText)

            CardSectionDivider(horizontalPadding: 0)

            Text(link.reason)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .lineSpacing(vocabSkin.metrics.paragraphLineSpacing)
                .fixedSize(horizontal: false, vertical: true)

            Spacer()

            Button {
                dismiss()
                onNavigate()
            } label: {
                HStack(spacing: 6) {
                    Text("查看詳情".localized)
                    Image(systemName: "arrow.up.right")
                        .font(vocabSkin.typography.iconTiny)
                }
                .frame(maxWidth: .infinity)
            }
            .buttonStyle(.ghost(vocabSkin.palette.primaryText))
        }
        .padding(vocabSkin.metrics.cardBlockPadding)
        .vocabCanvasBackground()
    }
}
