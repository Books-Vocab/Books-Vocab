import SwiftUI

/// The "create and link" entry of the Add Link sheet (#2037).
///
/// Two lines: the full action sentence (`addLink.create.title`) and the notebook
/// the new card is added to (`addLink.create.notebook`). A `Button` merges its
/// children into one accessibility element, so each line is also mirrored under
/// its own id (as a value) for UI tests; the button itself keeps `addLink.create`
/// and its label contains both words.
struct AddLinkCreateRow: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let title: String
    let notebookLine: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: appSkin.spacing.inlineGap) {
                Image(systemName: "plus.circle.fill")
                    .foregroundStyle(appSkin.palette.accent)
                VStack(alignment: .leading, spacing: AppSpacing.microGap) {
                    Text(title)
                        .foregroundStyle(appSkin.palette.primaryText)
                        .lineLimit(2)
                        .truncationMode(.tail)
                        .multilineTextAlignment(.leading)
                    Text(notebookLine)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .lineLimit(1)
                        .truncationMode(.tail)
                }
                Spacer(minLength: 0)
            }
            .contentShape(Rectangle())
        }
        .accessibilityIdentifier("addLink.create")
        .background(alignment: .topLeading) {
            ZStack {
                marker("addLink.create.title", value: title)
                marker("addLink.create.notebook", value: notebookLine)
            }
        }
        // Text changes while typing (the word is in the sentence): fade, don't jump.
        .animation(AppMotion.contentFade, value: title)
        .animation(AppMotion.contentFade, value: notebookLine)
        .enableInjection()
    }

    private func marker(_ identifier: String, value: String) -> some View {
        Color.clear
            .frame(width: 1, height: 1)
            .accessibilityElement()
            .accessibilityIdentifier(identifier)
            .accessibilityValue(value)
    }
}
