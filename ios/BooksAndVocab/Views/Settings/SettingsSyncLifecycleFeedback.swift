import SwiftUI

/// Terminal feedback stays outside the sync button so retry and dismiss remain
/// independently accessible while the button itself is disabled during a round.
struct SettingsSyncLifecycleFeedback: View {
    @ObserveInjection private var inject
    @Environment(\.appTheme) private var appTheme
    @Environment(\.appSkin) private var appSkin

    let lifecycle: SettingsSyncLifecycle
    let actions: SettingsPresenterActions
    let attempt: Int
    let dataOutcome: SettingsSyncDataOutcome
    let evidence: SettingsSyncLifecycleEvidence?

    var body: some View {
        switch lifecycle {
        case .terminalSuccess:
            feedback(
                title: L10n.string("同步完成"),
                message: nil,
                tone: appSkin.palette.success,
                systemImage: "checkmark.circle.fill",
                primaryTitle: L10n.string("關閉"),
                primaryIdentifier: "settings.syncLifecycle.dismissButton",
                primaryAction: actions.dismissSyncStatus,
                secondaryTitle: nil,
                secondaryIdentifier: nil,
                secondaryAction: nil,
                attempt: attempt,
                dataOutcome: dataOutcome,
                evidence: evidence,
                accessibilityValue: L10n.string("同步完成")
            )
        case .terminalError(let message):
            let copy = SettingsSyncLifecycleFeedbackCopy.terminalError(
                dataOutcome: dataOutcome,
                message: message
            )
            feedback(
                title: copy.title,
                message: copy.message,
                tone: appTheme.palette.warning,
                systemImage: "exclamationmark.triangle.fill",
                primaryTitle: L10n.string("重試"),
                primaryIdentifier: "settings.syncLifecycle.retryButton",
                primaryAction: actions.retrySync,
                secondaryTitle: L10n.string("關閉"),
                secondaryIdentifier: "settings.syncLifecycle.dismissButton",
                secondaryAction: actions.dismissSyncStatus,
                attempt: attempt,
                dataOutcome: dataOutcome,
                evidence: evidence,
                accessibilityValue: copy.accessibilityValue
            )
        case .idle, .syncing, .retry, .dismissed:
            EmptyView()
        }
    }

    private func feedback(
        title: String,
        message: String?,
        tone: Color,
        systemImage: String,
        primaryTitle: String,
        primaryIdentifier: String,
        primaryAction: @escaping () -> Void,
        secondaryTitle: String?,
        secondaryIdentifier: String?,
        secondaryAction: (() -> Void)?,
        attempt: Int,
        dataOutcome: SettingsSyncDataOutcome,
        evidence: SettingsSyncLifecycleEvidence?,
        accessibilityValue: String
    ) -> some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.tinyGap) {
            HStack(spacing: appSkin.spacing.inlineGap) {
                Image(systemName: systemImage)
                    .foregroundStyle(tone)
                Text(title)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(tone)
                    .accessibilityIdentifier("settings.syncLifecycle.status")
            }

            if let message {
                Text(message)
                    .font(appSkin.typography.caption)
                    .foregroundStyle(appSkin.palette.secondaryText)
                    .lineLimit(3)
                    .accessibilityIdentifier("settings.syncLifecycle.message")
            }

            Text("terminal=\(terminalName);attempt=\(attempt);dataOutcome=\(dataOutcome.rawValue)")
                .font(appSkin.typography.caption)
                .foregroundStyle(.clear)
                .frame(width: 1, height: 1)
                .accessibilityIdentifier("settings.syncLifecycle.terminalMarker")

#if DEBUG
            if let evidence {
                // i18n-allow: machine-readable DEBUG UI evidence marker
                Text(evidence.marker)
                    .foregroundStyle(.clear)
                    .frame(width: 1, height: 1)
                    .accessibilityIdentifier("settings.syncLifecycle.evidence")
            }
#endif

            HStack(spacing: appSkin.spacing.inlineGap) {
                Button(primaryTitle, action: primaryAction)
                    .buttonStyle(.appCompactAction(.primary))
                    .accessibilityIdentifier(primaryIdentifier)

                if let secondaryTitle, let secondaryIdentifier, let secondaryAction {
                    Button(secondaryTitle, action: secondaryAction)
                        .buttonStyle(.appCompactAction(.outline))
                        .accessibilityIdentifier(secondaryIdentifier)
                }
            }
        }
        .padding(.horizontal, appSkin.spacing.cardPadding)
        .padding(.vertical, appSkin.spacing.tinyGap)
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("settings.syncLifecycle")
        .accessibilityValue(Text(accessibilityValue))
        .transition(.statusRowReveal)
        .animation(AppMotion.feedbackPulse, value: lifecycle)
        .enableInjection()
    }

    private var terminalName: String {
        switch lifecycle {
        case .terminalSuccess: return "terminalSuccess"
        case .terminalError: return "terminalError"
        default: return "nonTerminal"
        }
    }
}

private struct SettingsSyncLifecycleFeedbackCopy {
    let title: String
    let message: String
    let accessibilityValue: String

    static func terminalError(
        dataOutcome: SettingsSyncDataOutcome,
        message: String
    ) -> Self {
        switch dataOutcome {
        case .partial:
            let retryNotice = L10n.string("部分項目未成功同步，可直接再次重試。")
            let detail = message == L10n.string("同步失敗") ? nil : message
            return Self(
                title: L10n.string("部分同步完成"),
                message: [retryNotice, detail]
                    .compactMap { $0 }
                    .joined(separator: "\n"),
                accessibilityValue: retryNotice
            )
        case .none, .complete:
            return Self(
                title: L10n.string("同步失敗"),
                message: message,
                accessibilityValue: L10n.string("同步失敗")
            )
        }
    }
}
