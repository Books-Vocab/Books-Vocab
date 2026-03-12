import SwiftUI

extension SettingsPresenter {

    // MARK: - Quota Row

    var quotaRow: some View {
        VStack(spacing: 0) {
            SettingsRow(icon: "gauge.with.dots.needle.bottom.50percent", label: "今日額度".localized) {
                HStack(spacing: 6) {
                    Text(quotaStore.isExhausted
                         ? quotaStore.resetText
                         : "\(Int(quotaStore.fraction * 100))%")
                        .font(vocabSkin.typography.caption)
                        .foregroundStyle(quotaTextColor)
                        .lineLimit(1)
                }
            }

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                        .fill(quotaBarColor.opacity(0.15))

                    RoundedRectangle(cornerRadius: 1.5, style: .continuous)
                        .fill(quotaBarColor)
                        .frame(width: geo.size.width * quotaStore.fraction)
                        .animation(AppMotion.standardSpring, value: quotaStore.fraction)
                }
            }
            .frame(height: 3)
            .padding(.horizontal, vocabSkin.spacing.cardPadding)
            .padding(.bottom, vocabSkin.spacing.tinyGap)
        }
    }

    var quotaBarColor: Color {
        switch quotaStore.level {
        case .normal:    return vocabSkin.palette.success
        case .warning:   return appTheme.palette.warning
        case .critical:  return vocabSkin.palette.destructive
        case .exhausted: return vocabSkin.palette.destructive
        }
    }

    var quotaTextColor: Color {
        switch quotaStore.level {
        case .normal:    return vocabSkin.palette.secondaryText
        case .warning:   return appTheme.palette.warning
        case .critical:  return vocabSkin.palette.destructive
        case .exhausted: return vocabSkin.palette.destructive
        }
    }
}
