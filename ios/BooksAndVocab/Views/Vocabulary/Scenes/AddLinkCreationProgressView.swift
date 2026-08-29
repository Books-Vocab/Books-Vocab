import SwiftUI

/// Missing-target Add Link progress surface using the shared sync panel.
struct AddLinkCreationProgressView: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let coordinator: AddLinkCreationCoordinator
    var onRetry: (() -> Void)? = nil
    let attempt: Int

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.tinyGap) {
            if let message = coordinator.message {
                if coordinator.phase == .failed {
                    AppBanner(message: message, systemImage: bannerSystemImage)
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier("addLink.creation.error")
                } else {
                    AppBanner(message: message, systemImage: bannerSystemImage)
                }
                if coordinator.phase == .failed, let onRetry {
                    Button(L10n.string("重試"), action: onRetry)
                        .buttonStyle(.appCompactAction(.primary))
                        .accessibilityIdentifier("addLink.creation.retry")
                }
            }
            SettingsSyncProgressPanel(steps: coordinator.steps, fraction: coordinator.fraction)
        }
        .padding(.vertical, appSkin.spacing.tinyGap)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("addLink.creation.progress")
        .accessibilityValue("attempt-\(attempt)")
        .enableInjection()
    }

    private var bannerSystemImage: String {
        switch coordinator.phase {
        case .succeeded: return "checkmark.circle"
        case .succeededWithWarnings, .failed, .blocked: return "exclamationmark.triangle"
        default: return "arrow.triangle.2.circlepath"
        }
    }
}
