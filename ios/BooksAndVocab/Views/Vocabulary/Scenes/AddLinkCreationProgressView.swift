import SwiftUI

/// Missing-target Add Link progress surface using the shared sync panel.
///
/// Terminal states keep the user in control: a failure names its reason and
/// offers retry (only when retrying can help) plus a way back to search; a
/// partial success lists what did not complete and waits for retry or done.
struct AddLinkCreationProgressView: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin

    let coordinator: AddLinkCreationCoordinator
    var onRetry: (() -> Void)? = nil
    let attempt: Int
    /// Warning state: the user accepts the partial result and closes.
    var onDone: (() -> Void)? = nil
    /// Failed state: leave the failure and pick or type another word.
    var onBackToSearch: (() -> Void)? = nil

    private var isWarning: Bool { coordinator.phase == .succeededWithWarnings }
    private var isFailed: Bool { coordinator.phase == .failed }
    private var canRetry: Bool {
        if isWarning { return !coordinator.isRetryingWarnings }
        return isFailed && coordinator.failure?.isRetryable != false
    }

    var body: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.tinyGap) {
            if let message = coordinator.message {
                if coordinator.phase == .failed || coordinator.phase == .succeededWithWarnings {
                    VocabStateMessageCard(title: message, systemImage: bannerSystemImage)
                        .transition(.statusRowReveal)
                        .accessibilityElement(children: .contain)
                        .accessibilityIdentifier(
                            coordinator.phase == .succeededWithWarnings
                                ? "addLink.creation.warning"
                                : "addLink.creation.error"
                        )
                } else {
                    // In-flight status: the progress panel below owns the lifecycle, so the
                    // line is plain status text, not a banner.
                    Text(message)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                }
                if isFailed, let failure = coordinator.failure {
                    Color.clear
                        .frame(width: 1, height: 1)
                        .accessibilityElement()
                        .accessibilityIdentifier("addLink.error.reason")
                        .accessibilityValue(failure.reason)
                }
                if isWarning {
                    ForEach(coordinator.warnings, id: \.self) { warning in
                        Label(warning.message, systemImage: "exclamationmark.circle")
                            .font(appSkin.typography.caption)
                            .foregroundStyle(appSkin.palette.secondaryText)
                            .fixedSize(horizontal: false, vertical: true)
                            .accessibilityIdentifier("addLink.creation.warning.item.\(warning.rawValue)")
                    }
                }
                actions
            }
            SettingsSyncProgressPanel(steps: coordinator.steps, fraction: coordinator.fraction)
        }
        .padding(.vertical, appSkin.spacing.tinyGap)
        .animation(AppMotion.phaseChange, value: coordinator.phase)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("addLink.creation.progress")
        .accessibilityValue("attempt-\(attempt)")
        .enableInjection()
    }

    @ViewBuilder
    private var actions: some View {
        if isFailed || isWarning {
            HStack(spacing: appSkin.spacing.inlineGap) {
                if let onRetry, canRetry || coordinator.isRetryingWarnings {
                    Button(L10n.string("重試"), action: onRetry)
                        .buttonStyle(.appCompactAction(.primary))
                        .disabled(!canRetry)
                        .accessibilityIdentifier("addLink.creation.retry")
                }
                if isWarning, let onDone {
                    Button(L10n.string("完成"), action: onDone)
                        .buttonStyle(.appCompactAction(.neutral))
                        .accessibilityIdentifier("addLink.creation.warning.done")
                }
                if isFailed, let onBackToSearch {
                    Button(L10n.string("addLink.creation.backToSearch"), action: onBackToSearch)
                        .buttonStyle(.appCompactAction(.neutral))
                        .accessibilityIdentifier("addLink.creation.backToSearch")
                }
            }
        }
    }

    private var bannerSystemImage: String {
        switch coordinator.phase {
        case .succeeded: return "checkmark.circle"
        case .succeededWithWarnings, .failed, .blocked: return "exclamationmark.triangle"
        default: return "arrow.triangle.2.circlepath"
        }
    }
}
