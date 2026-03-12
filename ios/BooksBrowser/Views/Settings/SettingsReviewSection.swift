import SwiftUI

struct SettingsReviewSection: View {
    @Environment(\.vocabSkin) private var vocabSkin
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore

    var body: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                modeSection
                customParamsSection
                footerSection
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppShellMetrics.pageTopPadding)
            .padding(.bottom, AppShellMetrics.pageBottomPadding)
        }
        .background(vocabSkin.palette.pageBackground.ignoresSafeArea())
        .navigationTitle("複習節奏".localized)
        .navigationBarTitleDisplayMode(.inline)
    }

    // MARK: - Mode Section

    private var modeSection: some View {
        VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: "複習模式", icon: "timer")

            HStack(spacing: ReviewSettingsMetrics.modeTileGap) {
                ForEach(ReviewSettingsMode.allCases, id: \.rawValue) { mode in
                    modeTile(mode)
                }
            }

            SettingsSectionFooter("選擇符合學習節奏的模式，設定立即生效。")
        }
    }

    private func modeTile(_ mode: ReviewSettingsMode) -> some View {
        let isSelected = reviewSettingsStore.settings.mode == mode
        return Button {
            var updated = reviewSettingsStore.settings
            updated.mode = mode
            reviewSettingsStore.update(updated)
        } label: {
            SettingsSelectionTile(isSelected: isSelected) {
                VStack(alignment: .leading, spacing: ReviewSettingsMetrics.modeTileContentGap) {
                    Image(systemName: mode.icon)
                        .font(vocabSkin.typography.iconToolbar)
                    Text(mode.displayName)
                        .font(vocabSkin.typography.body.weight(isSelected ? .semibold : .regular))
                }
            }
            .foregroundStyle(isSelected ? vocabSkin.palette.primaryText : vocabSkin.palette.secondaryText)
        }
        .buttonStyle(.plain)
    }

    // MARK: - Custom Params Section

    @ViewBuilder
    private var customParamsSection: some View {
        if reviewSettingsStore.settings.mode == .custom {
            VStack(alignment: .leading, spacing: vocabSkin.spacing.sectionGap) {
                SettingsSectionHeader(title: "自訂參數", icon: "slider.horizontal.3")

                VStack(spacing: 0) {
                    paramRow(
                        label: "初始間隔",
                        value: formatHours(reviewSettingsStore.settings.customInitialIntervalHours),
                        onDecrement: { adjustParam(\.customInitialIntervalHours, by: -4, min: 4, max: 72) },
                        onIncrement: { adjustParam(\.customInitialIntervalHours, by: 4, min: 4, max: 72) },
                        canDecrement: reviewSettingsStore.settings.customInitialIntervalHours > 4,
                        canIncrement: reviewSettingsStore.settings.customInitialIntervalHours < 72
                    )

                    SettingsDivider()

                    paramRow(
                        label: "記得倍率",
                        value: formatMultiplier(reviewSettingsStore.settings.customRememberedMultiplier),
                        onDecrement: { adjustParam(\.customRememberedMultiplier, by: -0.1, min: 1.1, max: 5.0) },
                        onIncrement: { adjustParam(\.customRememberedMultiplier, by: 0.1, min: 1.1, max: 5.0) },
                        canDecrement: reviewSettingsStore.settings.customRememberedMultiplier > 1.1 + 0.001,
                        canIncrement: reviewSettingsStore.settings.customRememberedMultiplier < 5.0 - 0.001
                    )

                    SettingsDivider()

                    paramRow(
                        label: "忘記倍率",
                        value: formatMultiplier(reviewSettingsStore.settings.customForgotMultiplier),
                        onDecrement: { adjustParam(\.customForgotMultiplier, by: -0.05, min: 0.1, max: 0.9) },
                        onIncrement: { adjustParam(\.customForgotMultiplier, by: 0.05, min: 0.1, max: 0.9) },
                        canDecrement: reviewSettingsStore.settings.customForgotMultiplier > 0.1 + 0.001,
                        canIncrement: reviewSettingsStore.settings.customForgotMultiplier < 0.9 - 0.001
                    )

                    SettingsDivider()

                    paramRow(
                        label: "最短間隔",
                        value: formatHours(reviewSettingsStore.settings.customMinimumIntervalHours),
                        onDecrement: { adjustParam(\.customMinimumIntervalHours, by: -2, min: 2, max: 24) },
                        onIncrement: { adjustParam(\.customMinimumIntervalHours, by: 2, min: 2, max: 24) },
                        canDecrement: reviewSettingsStore.settings.customMinimumIntervalHours > 2,
                        canIncrement: reviewSettingsStore.settings.customMinimumIntervalHours < 24
                    )

                    SettingsDivider()

                    paramRow(
                        label: "最長間隔",
                        value: formatHours(reviewSettingsStore.settings.customMaximumIntervalHours),
                        onDecrement: { adjustParam(\.customMaximumIntervalHours, by: -120, min: 120, max: 8760) },
                        onIncrement: { adjustParam(\.customMaximumIntervalHours, by: 120, min: 120, max: 8760) },
                        canDecrement: reviewSettingsStore.settings.customMaximumIntervalHours > 120,
                        canIncrement: reviewSettingsStore.settings.customMaximumIntervalHours < 8760
                    )
                }
                .settingsCard()
            }
            .transition(.statusRowReveal)
            .animation(AppMotion.phaseChange, value: reviewSettingsStore.settings.mode)
        }
    }

    private func paramRow(
        label: String,
        value: String,
        onDecrement: @escaping () -> Void,
        onIncrement: @escaping () -> Void,
        canDecrement: Bool,
        canIncrement: Bool
    ) -> some View {
        HStack(spacing: 0) {
            Text(label.localized)
                .font(vocabSkin.typography.body)
                .foregroundStyle(vocabSkin.palette.primaryText)

            Spacer()

            HStack(spacing: ReviewSettingsMetrics.stepperGap) {
                SettingsStepperIconButton(systemImage: "minus", enabled: canDecrement, action: onDecrement)

                Text(value)
                    .font(vocabSkin.typography.monoBodyStrong)
                    .foregroundStyle(vocabSkin.palette.primaryText)
                    .frame(minWidth: ReviewSettingsMetrics.valueMinWidth, alignment: .center)

                SettingsStepperIconButton(systemImage: "plus", enabled: canIncrement, action: onIncrement)
            }
        }
        .padding(.horizontal, vocabSkin.spacing.cardPadding)
        .padding(.vertical, vocabSkin.spacing.controlVerticalPadding)
    }

    // MARK: - Footer

    private var footerSection: some View {
        let s = reviewSettingsStore.settings
        let footerText = L10n.format(
            "目前生效：初始 %@・記得 %@・忘記 %@・最短 %@・最長 %@",
            formatHours(s.effectiveInitialIntervalHours),
            formatMultiplier(s.effectiveRememberedMultiplier),
            formatMultiplier(s.effectiveForgotMultiplier),
            formatHours(s.effectiveMinimumIntervalHours),
            formatHours(s.effectiveMaximumIntervalHours)
        )
        return SettingsSectionFooter(footerText)
    }

    // MARK: - Helpers

    private func formatHours(_ hours: Double) -> String {
        if hours >= 24 && hours.truncatingRemainder(dividingBy: 24) == 0 {
            return "\(Int(hours / 24))" + "天".localized
        }
        return "\(Int(hours))h"
    }

    private func formatMultiplier(_ v: Double) -> String {
        String(format: "%.2f×", v)
    }

    private func adjustParam(_ keyPath: WritableKeyPath<ReviewSettings, Double>, by delta: Double, min: Double, max: Double) {
        var updated = reviewSettingsStore.settings
        let newValue = (updated[keyPath: keyPath] + delta).rounded(toDecimalPlaces: 10)
        updated[keyPath: keyPath] = Swift.min(max, Swift.max(min, newValue))
        reviewSettingsStore.update(updated)
    }
}

private extension Double {
    func rounded(toDecimalPlaces places: Int) -> Double {
        let factor = pow(10.0, Double(places))
        return (self * factor).rounded() / factor
    }
}

private enum ReviewSettingsMetrics {
    static let modeTileGap: CGFloat = 10
    static let modeTileContentGap: CGFloat = 8
    static let stepperGap: CGFloat = 12
    static let valueMinWidth: CGFloat = 52
}

// MARK: - Preview

#Preview("寬鬆模式") {
    AppThemeContainer {
        NavigationStack {
            SettingsReviewSection()
        }
    }
    .environment(\.reviewSettingsStore, ReviewSettingsStore(previewSettings: ReviewSettings(
        mode: .relaxed,
        customInitialIntervalHours: 12,
        customRememberedMultiplier: 1.9,
        customForgotMultiplier: 0.45,
        customMinimumIntervalHours: 6,
        customMaximumIntervalHours: 1440
    )))
}

#Preview("自訂模式") {
    AppThemeContainer {
        NavigationStack {
            SettingsReviewSection()
        }
    }
    .environment(\.reviewSettingsStore, ReviewSettingsStore(previewSettings: ReviewSettings(
        mode: .custom,
        customInitialIntervalHours: 24,
        customRememberedMultiplier: 2.1,
        customForgotMultiplier: 0.35,
        customMinimumIntervalHours: 4,
        customMaximumIntervalHours: 2160
    )))
}

#Preview("密集模式") {
    AppThemeContainer {
        NavigationStack {
            SettingsReviewSection()
        }
    }
    .environment(\.reviewSettingsStore, ReviewSettingsStore(previewSettings: ReviewSettings(
        mode: .intensive,
        customInitialIntervalHours: 12,
        customRememberedMultiplier: 1.9,
        customForgotMultiplier: 0.45,
        customMinimumIntervalHours: 6,
        customMaximumIntervalHours: 1440
    )))
}

#Preview("自訂模式") {
    AppThemeContainer {
        NavigationStack {
            SettingsReviewSection()
        }
    }
    .environment(\.reviewSettingsStore, ReviewSettingsStore(previewSettings: ReviewSettings(
        mode: .custom,
        customInitialIntervalHours: 12,
        customRememberedMultiplier: 1.9,
        customForgotMultiplier: 0.45,
        customMinimumIntervalHours: 6,
        customMaximumIntervalHours: 1440
    )))
}
