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
    /// Brief emphasis (#2038): Return on a word nothing has points here instead of creating.
    var isHighlighted = false
    /// Latched count of flashes this row has actually rendered. The flash lasts ~1.4s, shorter
    /// than a UI test's poll latency, so tests read this count instead of `isHighlighted`.
    /// Counted here (not in the parent) so the marker proves the row rendered the highlight.
    @State private var shownPulses = 0
    /// Why the entry cannot be used right now (offline, #2039). The entry stays
    /// listed — disabled and explained — instead of disappearing.
    var disabledReason: String? = nil
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
                    Text(disabledReason ?? notebookLine)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .lineLimit(disabledReason == nil ? 1 : 2)
                        .truncationMode(.tail)
                }
                Spacer(minLength: 0)
            }
            .contentShape(Rectangle())
        }
        .accessibilityIdentifier("addLink.create")
        .background {
            AppRoundedRect(roundness: AppRoundness.control)
                .fill(appSkin.palette.accent.opacity(isHighlighted ? 0.14 : 0))
        }
        .background(alignment: .topLeading) {
            ZStack {
                marker("addLink.create.title", value: title)
                marker("addLink.create.notebook", value: notebookLine)
                marker("addLink.create.highlight", value: isHighlighted ? "on" : "off")
                marker("addLink.create.highlightPulses", value: String(shownPulses))
                if let disabledReason {
                    marker("addLink.create.disabledReason", value: disabledReason)
                }
            }
        }
        .animation(AppMotion.contentFade, value: disabledReason)
        .animation(AppMotion.feedbackPulse, value: isHighlighted)
        .onChange(of: isHighlighted) { _, on in
            if on { shownPulses += 1 }
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
