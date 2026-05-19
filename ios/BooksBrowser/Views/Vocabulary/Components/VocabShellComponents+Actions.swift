import SwiftUI

// MARK: - Buttons, Headers, Sliders, Sort, Metric Cards

struct VocabInlineActionButton: View {
    @Environment(\.appSkin) private var appSkin
    let title: String
    var tone: Color? = nil
    var action: () -> Void

    var body: some View {
        Button(title.localized, action: action)
            .font(appSkin.typography.body)
            .foregroundStyle(tone ?? appSkin.palette.accent)
            .buttonStyle(.plain)
    }
}

struct VocabSectionHeader: View {
    @Environment(\.appSkin) private var appSkin
    let title: String
    var systemImage: String? = nil
    var trailingText: String? = nil

    var body: some View {
        HStack(spacing: appSkin.spacing.microGap) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(appSkin.typography.iconTiny)
            }

            Text(title.localized)
                .font(appSkin.typography.caption)
                .tracking(appSkin.metrics.labelTracking)

            if let trailingText {
                Text(trailingText.localized)
                    .font(appSkin.typography.monoLabel)
                    .foregroundStyle(appSkin.palette.quaternaryText)
            }

            Spacer()
        }
        .foregroundStyle(appSkin.palette.tertiaryText)
    }
}

struct VocabSliderRow: View {
    @Environment(\.appSkin) private var appSkin
    let label: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    let format: String
    var labelWidth: CGFloat = 64
    var valueWidth: CGFloat = 42

    var body: some View {
        HStack(spacing: appSkin.spacing.inlineGap) {
            Text(label.localized)
                .font(appSkin.typography.caption)
                .foregroundStyle(appSkin.palette.primaryText)
                .frame(width: labelWidth, alignment: .leading)

            Slider(value: $value, in: range)

            Text(String(format: format, value))
                .font(appSkin.typography.monoLabel)
                .monospacedDigit()
                .foregroundStyle(appSkin.palette.secondaryText)
                .frame(width: valueWidth, alignment: .trailing)
        }
        .frame(height: appSkin.metrics.tabSelectorHeight)
    }
}

struct VocabMetricHeroCard: View {
    @Environment(\.appSkin) private var appSkin
    let title: String
    let description: String
    let value: String

    var body: some View {
        VocabCard {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(title.localized)
                        .font(appSkin.typography.sectionTitle)
                        .foregroundStyle(appSkin.palette.primaryText)

                    Text(description.localized)
                        .font(appSkin.typography.body)
                        .foregroundStyle(appSkin.palette.secondaryText)
                }

                Spacer()

                Text(value)
                    .font(appSkin.typography.numericHero)
                    .foregroundStyle(appSkin.palette.quaternaryText)
                    .monospacedDigit()
            }
        }
    }
}

struct VocabAccessoryIconButton: View {
    @Environment(\.appSkin) private var appSkin
    let systemImage: String
    let tone: Color
    var background: Color? = nil
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(appSkin.typography.iconToolbar)
                .foregroundStyle(tone)
                .frame(width: appSkin.metrics.chromeButtonSize, height: appSkin.metrics.chromeButtonSize)
                .background(
                    RoundedRectangle(cornerRadius: appSkin.radii.tiny, style: .continuous)
                        .fill(background ?? appSkin.palette.mutedFill)
                )
        }
        .buttonStyle(.plain)
    }
}

struct VocabSortPill: View {
    @Environment(\.appSkin) private var appSkin
    @Binding var sortOption: KGVocabSortOption

    var body: some View {
        Menu {
            ForEach(KGVocabSortOption.allCases) { option in
                Button {
                    sortOption = option
                } label: {
                    Label(option.label, systemImage: option.systemImage)
                }
            }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "arrow.up.arrow.down")
                Text(sortOption.label)
            }
            .font(appSkin.typography.caption)
            .foregroundStyle(appSkin.palette.secondaryText)
            .padding(.horizontal, appSkin.spacing.compactChipHorizontalPadding)
            .padding(.vertical, appSkin.spacing.compactChipVerticalPadding)
            .background(
                Capsule(style: .continuous)
                    .fill(appSkin.palette.mutedFill)
            )
        }
        .accessibilityLabel(L10n.format("排序方式：%@", sortOption.label))
        .accessibilityHint("點兩下切換排序".localized)
    }
}
