import SwiftUI

// quota row 掛在 SettingsOtherSection（child View struct）；不得搬回
// SettingsPresenter — 見 SettingsOtherSection.swift 檔頭的 stack 約束。
extension SettingsOtherSection {

    // MARK: - Quota Row

    var quotaRow: some View {
        VStack(spacing: 0) {
            AppKeyValueRow(icon: "gauge.with.dots.needle.bottom.50percent", label: "今日額度".localized, style: .settings(appSkin)) {
                SettingsStatusValue(
                    text: quotaStore.isExhausted
                        ? quotaStore.resetText
                        : "\(Int(quotaStore.fraction * 100))%",
                    color: quotaTextColor
                )
            }

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: AppRadius.hairline, style: .continuous)
                        .fill(quotaBarColor.opacity(0.15))

                    RoundedRectangle(cornerRadius: AppRadius.hairline, style: .continuous)
                        .fill(quotaBarColor)
                        .frame(width: geo.size.width * quotaStore.fraction)
                        .animateSpring(quotaStore.fraction)
                }
            }
            .frame(height: 3)
            .padding(.horizontal, appSkin.spacing.cardPadding)
            .padding(.bottom, appSkin.spacing.tinyGap)
        }
    }

    var quotaBarColor: Color {
        switch quotaStore.level {
        case .normal:    return appSkin.palette.success
        case .warning:   return appTheme.palette.warning
        case .critical:  return appSkin.palette.destructive
        case .exhausted: return appSkin.palette.destructive
        }
    }

    var quotaTextColor: Color {
        switch quotaStore.level {
        case .normal:    return appSkin.palette.secondaryText
        case .warning:   return appTheme.palette.warning
        case .critical:  return appSkin.palette.destructive
        case .exhausted: return appSkin.palette.destructive
        }
    }
}
