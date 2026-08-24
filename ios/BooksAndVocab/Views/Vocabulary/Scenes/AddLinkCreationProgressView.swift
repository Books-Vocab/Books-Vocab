import SwiftUI

/// Missing-target Add Link progress surface using the shared sync panel.
struct AddLinkCreationProgressView: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let coordinator: AddLinkCreationCoordinator

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.tinyGap) {
            if let message = coordinator.message {
                AppBanner(message: message, systemImage: bannerSystemImage)
            }
            SettingsSyncProgressPanel(steps: coordinator.steps, fraction: coordinator.fraction)
        }
        .padding(.vertical, appSkin.spacing.tinyGap)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("addLink.creation.progress")
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
