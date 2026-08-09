import SwiftUI

/// 複習節奏 — 三個設定頁共用的**原生**心智模型（見 APP-20260808-240a94 / f0770b）：
/// 容器 = `Form`，分組 = `Section` + `SettingsSectionHeader` / `SettingsSectionFooter`，
/// 選擇 = `Picker`，數值 = `Stepper`，開關 = `Toggle`。分隔線、列高、選取態一律由平台畫。
///
/// 具名承認的代價：改成 `Form` 後，襯線標題、自訂間距節奏與 selection tile 的
/// icon+文字雙行版面被系統列樣式吃掉（頁面背景亦交還系統 grouped background）。
/// 這是「一致性優先」的直接後果，**不要**在 Section 內重新自繪把個性救回來。
struct SettingsReviewSection: View {
    @ObserveInjection private var inject
    @Environment(\.reviewSettingsStore) private var reviewSettingsStore

    /// 樂觀寫本地+iCloud + push 後端 + 失敗 rollback 全由 coordinator 一條龍處理。
    /// preview / 無 network 場景用 no-op default。
    var onPauseChanged: (Bool) async -> Void = { _ in }
    /// mode / 自訂 SRS 參數變更:同樣交 coordinator 一條龍(樂觀+push+rollback)。
    var onModeChanged: (ReviewSettings) async -> Void = { _ in }

    var body: some View {
        Form {
            pauseSection
            modeSection
            customParamsSection
            effectiveSummarySection
        }
        .navigationTitle(L10n.string("複習節奏"))
        .inlineNavigationBarTitle()
        .enableInjection()
    }

    // MARK: - Pause Section

    private var pauseSection: some View {
        Section {
            Toggle(isOn: pauseBinding) {
                Text(L10n.string("凍結複習時鐘"))
            }
            .accessibilityIdentifier("settings.review.pauseToggle")
        } header: {
            SettingsSectionHeader(title: L10n.string("暫停進度"), icon: "pause.circle")
        } footer: {
            SettingsSectionFooter(pauseDescription)
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

    /// `.inline` 而非 `.segmented`：三個模式各帶 icon 需要列寬，而 XCTest 對 inline
    /// picker 的每一列都以 button 曝光，`settings.review.modeTile.<raw>` 這個
    /// UI-test 契約（SettingsSheetPage.reviewModeTile）才穩定成立。
    private var modeSection: some View {
        Section {
            Picker(selection: modeBinding) {
                ForEach(ReviewSettingsMode.allCases, id: \.rawValue) { mode in
                    Label(mode.displayName, systemImage: mode.icon)
                        .tag(mode)
                        .accessibilityIdentifier("settings.review.modeTile.\(mode.rawValue)")
                }
            } label: {
                Text(L10n.string("複習模式"))
            }
            .pickerStyle(.inline)
            .labelsHidden()
        } header: {
            SettingsSectionHeader(title: L10n.string("複習模式"), icon: "timer")
        } footer: {
            SettingsSectionFooter(L10n.string("選擇符合學習節奏的模式，設定立即生效。"))
        }
    }

    private var modeBinding: Binding<ReviewSettingsMode> {
        Binding(
            get: { reviewSettingsStore.settings.mode },
            set: { mode in
                var updated = reviewSettingsStore.settings
                updated.mode = mode
                Task { await onModeChanged(updated) }
            }
        )
    }

    // MARK: - Custom Params Section

    @ViewBuilder
    private var customParamsSection: some View {
        if reviewSettingsStore.settings.mode == .custom {
            Section {
                ParamRow(
                    label: L10n.string("初始間隔"),
                    value: formatHours(reviewSettingsStore.settings.customInitialIntervalHours),
                    onDecrement: { adjustParam(\.customInitialIntervalHours, by: -4, min: 4, max: 72) },
                    onIncrement: { adjustParam(\.customInitialIntervalHours, by: 4, min: 4, max: 72) },
                    canDecrement: reviewSettingsStore.settings.customInitialIntervalHours > 4,
                    canIncrement: reviewSettingsStore.settings.customInitialIntervalHours < 72
                )

                ParamRow(
                    label: L10n.string("記得倍率"),
                    value: formatMultiplier(reviewSettingsStore.settings.customRememberedMultiplier),
                    onDecrement: { adjustParam(\.customRememberedMultiplier, by: -0.1, min: 1.1, max: 5.0) },
                    onIncrement: { adjustParam(\.customRememberedMultiplier, by: 0.1, min: 1.1, max: 5.0) },
                    canDecrement: reviewSettingsStore.settings.customRememberedMultiplier > 1.1 + 0.001,
                    canIncrement: reviewSettingsStore.settings.customRememberedMultiplier < 5.0 - 0.001
                )

                ParamRow(
                    label: L10n.string("忘記倍率"),
                    value: formatMultiplier(reviewSettingsStore.settings.customForgotMultiplier),
                    onDecrement: { adjustParam(\.customForgotMultiplier, by: -0.05, min: 0.1, max: 0.9) },
                    onIncrement: { adjustParam(\.customForgotMultiplier, by: 0.05, min: 0.1, max: 0.9) },
                    canDecrement: reviewSettingsStore.settings.customForgotMultiplier > 0.1 + 0.001,
                    canIncrement: reviewSettingsStore.settings.customForgotMultiplier < 0.9 - 0.001
                )

                ParamRow(
                    label: L10n.string("最短間隔"),
                    value: formatHours(reviewSettingsStore.settings.customMinimumIntervalHours),
                    onDecrement: { adjustParam(\.customMinimumIntervalHours, by: -2, min: 2, max: 24) },
                    onIncrement: { adjustParam(\.customMinimumIntervalHours, by: 2, min: 2, max: 24) },
                    canDecrement: reviewSettingsStore.settings.customMinimumIntervalHours > 2,
                    canIncrement: reviewSettingsStore.settings.customMinimumIntervalHours < 24
                )

                ParamRow(
                    label: L10n.string("最長間隔"),
                    value: formatHours(reviewSettingsStore.settings.customMaximumIntervalHours),
                    onDecrement: { adjustParam(\.customMaximumIntervalHours, by: -120, min: 120, max: 8760) },
                    onIncrement: { adjustParam(\.customMaximumIntervalHours, by: 120, min: 120, max: 8760) },
                    canDecrement: reviewSettingsStore.settings.customMaximumIntervalHours > 120,
                    canIncrement: reviewSettingsStore.settings.customMaximumIntervalHours < 8760
                )
            } header: {
                SettingsSectionHeader(title: L10n.string("自訂參數"), icon: "slider.horizontal.3")
            }
        }
    }

    /// 一列 = 原生 `Stepper` 包一個 `LabeledContent`。上下界不再靠自繪按鈕的
    /// enabled 著色表達，而是把對應的 increment/decrement closure 傳 nil —— 平台
    /// 自己把那一半 stepper 變灰並停止觸發。
    ///
    /// `private`：injection_lint R1 對非 private 的 `struct …: View` 要求緊接一個
    /// hot-reload 觀測屬性，而本型別純粹是 row builder，沒有自己的注入生命週期。
    private struct ParamRow: View {
        let label: String
        let value: String
        let onDecrement: () -> Void
        let onIncrement: () -> Void
        let canDecrement: Bool
        let canIncrement: Bool

        var body: some View {
            Stepper(
                onIncrement: canIncrement ? onIncrement : nil,
                onDecrement: canDecrement ? onDecrement : nil
            ) {
                LabeledContent(label) {
                    Text(value).monospacedDigit()
                }
            }
        }
    }

    // MARK: - Footer

    /// 只有 footer 的 Section：目前生效值在 mode 切換時都要看得到，掛在
    /// 「自訂參數」底下會在非自訂模式一起消失。
    private var effectiveSummarySection: some View {
        Section {
            EmptyView()
        } footer: {
            SettingsSectionFooter(effectiveSummaryText)
        }
    }

    private var effectiveSummaryText: String {
        let s = reviewSettingsStore.settings
        return L10n.format(
            "目前生效：初始 %@・記得 %@・忘記 %@・最短 %@・最長 %@",
            formatHours(s.effectiveInitialIntervalHours),
            formatMultiplier(s.effectiveRememberedMultiplier),
            formatMultiplier(s.effectiveForgotMultiplier),
            formatHours(s.effectiveMinimumIntervalHours),
            formatHours(s.effectiveMaximumIntervalHours)
        )
    }

    // MARK: - Helpers

    private func formatHours(_ hours: Double) -> String {
        if hours >= 24 && hours.truncatingRemainder(dividingBy: 24) == 0 {
            return "\(Int(hours / 24))" + L10n.string("天")
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
