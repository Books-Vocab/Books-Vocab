import SwiftUI

struct SettingsReviewSection: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore

    /// 樂觀寫本地+iCloud + push 後端 + 失敗 rollback 全由 coordinator 一條龍處理。
    /// preview / 無 network 場景用 no-op default。
    var onPauseChanged: (Bool) async -> Void = { _ in }
    /// mode / 自訂 SRS 參數變更:同樣交 coordinator 一條龍(樂觀+push+rollback)。
    var onModeChanged: (ReviewSettings) async -> Void = { _ in }

    var body: some View {
        ScrollView {
            VStack(spacing: AppShellMetrics.sectionSpacing) {
                pauseSection
                modeSection
                customParamsSection
                footerSection
            }
            .padding(.horizontal, AppShellMetrics.pageHorizontalPadding)
            .padding(.top, AppShellMetrics.pageTopPadding)
            .padding(.bottom, AppShellMetrics.pageBottomPadding)
        }
        .background(appSkin.palette.pageBackground.ignoresSafeArea())
        .navigationTitle(L10n.string("複習節奏"))
        .inlineNavigationBarTitle()
        .enableInjection()
    }

    // MARK: - Pause Section

    private var pauseSection: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("暫停進度"), icon: "pause.circle")

            HStack(spacing: appSkin.spacing.inlineGap) {
                VStack(alignment: .leading, spacing: AppSpacing.s1) {
                    Text(L10n.string("凍結複習時鐘"))
                        .font(appSkin.typography.body.weight(.semibold))
                        .foregroundStyle(appSkin.palette.primaryText)

                    Text(pauseDescription.localized)
                        .font(appSkin.typography.caption)
                        .foregroundStyle(appSkin.palette.secondaryText)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: AppSpacing.s2)

                Toggle("", isOn: pauseBinding)
                    .labelsHidden()
                    .toggleStyle(SwitchToggleStyle(tint: appSkin.palette.accent))
            }
            .padding(.horizontal, appSkin.spacing.cardPadding)
            .padding(.vertical, appSkin.spacing.controlVerticalPadding)
            .settingsCard()
        }
    }

    private var pauseBinding: Binding<Bool> {
        Binding(
            get: { reviewSettingsStore.settings.isProgressPaused },
            set: { isPaused in
                // 樂觀更新 + push 後端 + 失敗 rollback 全交給 coordinator.updateReviewClock。
                Task { await onPauseChanged(isPaused) }
            }
        )
    }

    private var pauseDescription: String {
        guard reviewSettingsStore.settings.isProgressPaused else {
            return L10n.string("暫停後，到期計算會停在現在；已到期卡仍可手動複習。")
        }
        guard let pausedAt = reviewSettingsStore.settings.progressPausedAt else {
            return L10n.string("複習到期計算已暫停。")
        }
        return L10n.format(
            "目前停在 %@",
            LocaleAwareFormatter.shared.string(from: pausedAt, template: "yMMMd")
        )
    }

    // MARK: - Mode Section

    private var modeSection: some View {
        VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
            SettingsSectionHeader(title: L10n.string("複習模式"), icon: "timer")

            HStack(spacing: AppSettingsMetrics.reviewModeTileGap) {
                ForEach(ReviewSettingsMode.allCases, id: \.rawValue) { mode in
                    modeTile(mode)
                }
            }

            SettingsSectionFooter(L10n.string("選擇符合學習節奏的模式，設定立即生效。"))
        }
    }

    private func modeTile(_ mode: ReviewSettingsMode) -> some View {
        let isSelected = reviewSettingsStore.settings.mode == mode
        return Button {
            var updated = reviewSettingsStore.settings
            updated.mode = mode
            Task { await onModeChanged(updated) }
        } label: {
            SettingsSelectionTile(isSelected: isSelected) {
                VStack(alignment: .leading, spacing: AppSpacing.s2) {
                    Image(systemName: mode.icon)
                        .font(appSkin.typography.iconToolbar)
                    Text(mode.displayName)
                        .font(appSkin.typography.body.weight(isSelected ? .semibold : .regular))
                }
            }
            .foregroundStyle(isSelected ? appSkin.palette.primaryText : appSkin.palette.secondaryText)
        }
        .buttonStyle(.plain)
    }

    // MARK: - Custom Params Section

    @ViewBuilder
    private var customParamsSection: some View {
        if reviewSettingsStore.settings.mode == .custom {
            VStack(alignment: .leading, spacing: appSkin.spacing.sectionGap) {
                SettingsSectionHeader(title: L10n.string("自訂參數"), icon: "slider.horizontal.3")

                VStack(spacing: 0) {
                    ParamRow(
                        label: "初始間隔",
                        value: formatHours(reviewSettingsStore.settings.customInitialIntervalHours),
                        onDecrement: { adjustParam(\.customInitialIntervalHours, by: -4, min: 4, max: 72) },
                        onIncrement: { adjustParam(\.customInitialIntervalHours, by: 4, min: 4, max: 72) },
                        canDecrement: reviewSettingsStore.settings.customInitialIntervalHours > 4,
                        canIncrement: reviewSettingsStore.settings.customInitialIntervalHours < 72
                    )

                    SettingsDivider()

                    ParamRow(
                        label: "記得倍率",
                        value: formatMultiplier(reviewSettingsStore.settings.customRememberedMultiplier),
                        onDecrement: { adjustParam(\.customRememberedMultiplier, by: -0.1, min: 1.1, max: 5.0) },
                        onIncrement: { adjustParam(\.customRememberedMultiplier, by: 0.1, min: 1.1, max: 5.0) },
                        canDecrement: reviewSettingsStore.settings.customRememberedMultiplier > 1.1 + 0.001,
                        canIncrement: reviewSettingsStore.settings.customRememberedMultiplier < 5.0 - 0.001
                    )

                    SettingsDivider()

                    ParamRow(
                        label: "忘記倍率",
                        value: formatMultiplier(reviewSettingsStore.settings.customForgotMultiplier),
                        onDecrement: { adjustParam(\.customForgotMultiplier, by: -0.05, min: 0.1, max: 0.9) },
                        onIncrement: { adjustParam(\.customForgotMultiplier, by: 0.05, min: 0.1, max: 0.9) },
                        canDecrement: reviewSettingsStore.settings.customForgotMultiplier > 0.1 + 0.001,
                        canIncrement: reviewSettingsStore.settings.customForgotMultiplier < 0.9 - 0.001
                    )

                    SettingsDivider()

                    ParamRow(
                        label: "最短間隔",
                        value: formatHours(reviewSettingsStore.settings.customMinimumIntervalHours),
                        onDecrement: { adjustParam(\.customMinimumIntervalHours, by: -2, min: 2, max: 24) },
                        onIncrement: { adjustParam(\.customMinimumIntervalHours, by: 2, min: 2, max: 24) },
                        canDecrement: reviewSettingsStore.settings.customMinimumIntervalHours > 2,
                        canIncrement: reviewSettingsStore.settings.customMinimumIntervalHours < 24
                    )

                    SettingsDivider()

                    ParamRow(
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
        }
    }

    struct ParamRow: View {
        @Environment(\.appSkin) private var appSkin
        let label: String
        let value: String
        let onDecrement: () -> Void
        let onIncrement: () -> Void
        let canDecrement: Bool
        let canIncrement: Bool

        var body: some View {
            HStack(spacing: 0) {
                Text(label.localized)
                    .font(appSkin.typography.body)
                    .foregroundStyle(appSkin.palette.primaryText)

                Spacer()

                HStack(spacing: AppSettingsMetrics.reviewStepperGap) {
                    SettingsStepperIconButton(systemImage: "minus", enabled: canDecrement, action: onDecrement)

                    Text(value)
                        .font(appSkin.typography.monoBodyStrong)
                        .foregroundStyle(appSkin.palette.primaryText)
                        .frame(minWidth: AppSettingsMetrics.reviewValueMinWidth, alignment: .center)

                    SettingsStepperIconButton(systemImage: "plus", enabled: canIncrement, action: onIncrement)
                }
            }
            .padding(.horizontal, appSkin.spacing.cardPadding)
            .padding(.vertical, appSkin.spacing.controlVerticalPadding)
        }
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
        Task { await onModeChanged(updated) }
    }
}

private extension Double {
    func rounded(toDecimalPlaces places: Int) -> Double {
        let factor = pow(10.0, Double(places))
        return (self * factor).rounded() / factor
    }
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
    .environmentObject(AppAppearanceStore.preview)
}

#Preview("自訂模式 / 緊湊參數") {
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
    .environmentObject(AppAppearanceStore.preview)
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
    .environmentObject(AppAppearanceStore.preview)
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
    .environmentObject(AppAppearanceStore.preview)
}
