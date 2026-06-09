import SwiftUI
import Inject

// MARK: - Buttons, Headers, Sliders, Sort, Metric Cards

struct VocabInlineActionButton: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let title: String
    var tone: Color? = nil
    var action: () -> Void

    var body: some View {
        Button(title.localized, action: action)
            .font(appSkin.typography.body)
            .foregroundStyle(tone ?? appSkin.palette.accent)
            .buttonStyle(.plain)
            .enableInjection()
    }
}

struct VocabSectionHeader: View {
    @ObserveInjection private var inject
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
        .enableInjection()
    }
}

struct VocabSliderRow: View {
    @ObserveInjection private var inject
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
        .enableInjection()
    }
}

struct VocabAccessoryIconButton: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    let systemImage: String
    let tone: Color
    var background: Color? = nil
    let accessibilityLabel: String
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
        .accessibilityLabel(accessibilityLabel)
        .enableInjection()
    }
}

/// 內嵌於 chip+sort 列尾端的小型「開始複習」CTA pill。
///
/// 視覺上比 VocabSortPill 重(brandHero 填色 + onBrandHero 前景)以保留 primary action
/// 的層級，但尺寸跟 sort pill 同階 — 用 capsule + caption 字級 + compact 間距。
/// 用於 detail 頁(KGVocabPresenter)與 NotebookListView 頂部 section header (D4 editorial)。
struct VocabReviewCTAPill: View {
    @ObserveInjection private var inject
    @Environment(\.appSkin) private var appSkin
    @Environment(\.appTheme) private var appTheme

    let dueCount: Int
    let unlearnedCount: Int
    let onStartDue: () -> Void
    let onStartUnlearned: () -> Void
    let onStartMixed: () -> Void

    private var totalCount: Int { dueCount + unlearnedCount }
    private var hasBothTypes: Bool { dueCount > 0 && unlearnedCount > 0 }

    var body: some View {
        Group {
            if hasBothTypes {
                Menu {
                    Button {
                        onStartMixed()
                    } label: {
                        Label(L10n.format("全部複習（%@）", "\(totalCount)"), systemImage: "rectangle.stack")
                    }
                    Divider()
                    Button {
                        onStartDue()
                    } label: {
                        Label(L10n.format("到期複習（%@）", "\(dueCount)"), systemImage: "clock.badge")
                    }
                    Button {
                        onStartUnlearned()
                    } label: {
                        Label(L10n.format("未學複習（%@）", "\(unlearnedCount)"), systemImage: "sparkles")
                    }
                } label: { pillLabel(count: totalCount, systemImage: "play.fill") }
                .accessibilityLabel(L10n.format("開始複習，共 %@ 張", "\(totalCount)"))
            } else if dueCount > 0 {
                Button(action: onStartDue) {
                    pillLabel(count: dueCount, systemImage: "clock.badge")
                }
                .buttonStyle(.plain)
                .accessibilityLabel(L10n.format("開始到期複習，%@ 張", "\(dueCount)"))
            } else if unlearnedCount > 0 {
                Button(action: onStartUnlearned) {
                    pillLabel(count: unlearnedCount, systemImage: "sparkles")
                }
                .buttonStyle(.plain)
                .accessibilityLabel(L10n.format("開始未學複習，%@ 張", "\(unlearnedCount)"))
            }
        }
        .enableInjection()
    }

    private func pillLabel(count: Int, systemImage: String) -> some View {
        HStack(spacing: AppSpacing.microGap) {
            Image(systemName: systemImage)
            Text("\(count)")
                .monospacedDigit()
        }
        .font(appSkin.typography.caption)
        .foregroundStyle(AppColors.onBrandHero)
        .padding(.horizontal, appSkin.spacing.compactChipHorizontalPadding)
        .padding(.vertical, appSkin.spacing.compactChipVerticalPadding)
        .background(
            Capsule(style: .continuous)
                .fill(appTheme.palette.brandHero)
        )
    }
}

struct VocabSortPill: View {
    @ObserveInjection private var inject
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
            HStack(spacing: AppSpacing.s1) {
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
        .enableInjection()
    }
}
