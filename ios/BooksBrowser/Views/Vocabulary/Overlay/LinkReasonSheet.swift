import SwiftUI

struct LinkReasonSheet: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.dismiss) private var dismiss

    let link: KGCardLinkSummary
    let onNavigate: () -> Void
    var onHide: (() -> Void)?

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

            VStack(spacing: vocabSkin.spacing.inlineGap) {
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

                if let onHide {
                    Button {
                        dismiss()
                        onHide()
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "eye.slash")
                                .font(vocabSkin.typography.iconTiny)
                            Text("隱藏此連結".localized)
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.ghost(vocabSkin.palette.destructive))
                }
            }
        }
        .padding(vocabSkin.metrics.cardBlockPadding)
        .vocabCanvasBackground()
    }
}
