import SwiftUI

// MARK: - Buttons, Headers, Sliders, Sort, Metric Cards

struct VocabInlineActionButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    var tone: Color? = nil
    var action: () -> Void

    var body: some View {
        Button(title.localized, action: action)
            .font(vocabSkin.typography.body)
            .foregroundStyle(tone ?? vocabSkin.palette.accent)
            .buttonStyle(.plain)
    }
}

struct VocabSectionHeader: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    var systemImage: String? = nil
    var trailingText: String? = nil

    var body: some View {
        HStack(spacing: vocabSkin.spacing.microGap) {
            if let systemImage {
                Image(systemName: systemImage)
                    .font(vocabSkin.typography.iconTiny)
            }

            Text(title.localized)
                .font(vocabSkin.typography.captionStrong)
                .tracking(vocabSkin.metrics.labelTracking)

            if let trailingText {
                Text(trailingText.localized)
                    .font(vocabSkin.typography.monoLabel)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
            }

            Spacer()
        }
        .foregroundStyle(vocabSkin.palette.tertiaryText)
    }
}

struct VocabSliderRow: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let label: String
    @Binding var value: Double
    let range: ClosedRange<Double>
    let format: String
    var labelWidth: CGFloat = 64
    var valueWidth: CGFloat = 42

    var body: some View {
        HStack(spacing: vocabSkin.spacing.inlineGap) {
            Text(label.localized)
                .font(vocabSkin.typography.caption)
                .foregroundStyle(vocabSkin.palette.primaryText)
                .frame(width: labelWidth, alignment: .leading)

            Slider(value: $value, in: range)

            Text(String(format: format, value))
                .font(vocabSkin.typography.monoLabel)
                .monospacedDigit()
                .foregroundStyle(vocabSkin.palette.secondaryText)
                .frame(width: valueWidth, alignment: .trailing)
        }
        .frame(height: vocabSkin.metrics.tabSelectorHeight)
    }
}

struct VocabMetricHeroCard: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let title: String
    let description: String
    let value: String

    var body: some View {
        VocabCard {
            HStack(alignment: .firstTextBaseline) {
                VStack(alignment: .leading, spacing: 4) {
                    Text(title.localized)
                        .font(vocabSkin.typography.sectionTitle)
                        .foregroundStyle(vocabSkin.palette.primaryText)

                    Text(description.localized)
                        .font(vocabSkin.typography.body)
                        .foregroundStyle(vocabSkin.palette.secondaryText)
                }

                Spacer()

                Text(value)
                    .font(vocabSkin.typography.numericHero)
                    .foregroundStyle(vocabSkin.palette.quaternaryText)
                    .monospacedDigit()
            }
        }
    }
}

struct VocabAccessoryIconButton: View {
    @Environment(\.vocabSkin) private var vocabSkin
    let systemImage: String
    let tone: Color
    var background: Color? = nil
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(vocabSkin.typography.iconToolbar)
                .foregroundStyle(tone)
                .frame(width: vocabSkin.metrics.chromeButtonSize, height: vocabSkin.metrics.chromeButtonSize)
                .background(
                    RoundedRectangle(cornerRadius: vocabSkin.radii.tiny, style: .continuous)
                        .fill(background ?? vocabSkin.palette.mutedFill)
                )
        }
        .buttonStyle(.plain)
    }
}

struct VocabSortPill: View {
    @Environment(\.vocabSkin) private var vocabSkin
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
            .font(vocabSkin.typography.caption)
            .foregroundStyle(vocabSkin.palette.secondaryText)
            .padding(.horizontal, vocabSkin.spacing.compactChipHorizontalPadding)
            .padding(.vertical, vocabSkin.spacing.compactChipVerticalPadding)
            .background(
                RoundedRectangle(cornerRadius: vocabSkin.radii.control, style: .continuous)
                    .fill(vocabSkin.palette.mutedFill)
            )
        }
        .accessibilityLabel(L10n.format("排序方式：%@", sortOption.label))
        .accessibilityHint("點兩下切換排序".localized)
    }
}
